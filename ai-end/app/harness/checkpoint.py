"""
Checkpoint —— 状态持久化 + 断点恢复

设计：
- 每个 workflow 节点执行后写入 PG（含完整 state snapshot）
- 节点失败时 status='failed'，便于 retry 时跳过
- 恢复时按 (session_id, workflow_type, step_name) 唯一定位
- 同一 session 同一 step 多次执行会被 UPSERT 覆盖（幂等）

为什么用 JSONB 而不强 schema：
- LangGraph State 是动态 TypedDict
- JSONB 灵活，未来 schema 变了不破坏历史 checkpoint
"""

import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List

from app.tools.db import get_global_pool

logger = logging.getLogger(__name__)


def _record_checkpoint_metric(operation: str, status: str) -> None:
    """记录 checkpoint 操作到 Prometheus"""
    try:
        from app.utils.metrics import checkpoint_operations_total
        checkpoint_operations_total.labels(operation=operation, status=status).inc()
    except Exception:
        pass


@dataclass
class Checkpoint:
    """单次节点执行的快照"""
    session_id: str
    workflow_type: str
    step_name: str
    state_snapshot: Dict[str, Any]
    status: str = "completed"
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    checkpoint_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "session_id": self.session_id,
            "workflow_type": self.workflow_type,
            "step_name": self.step_name,
            "state_snapshot": self.state_snapshot,
            "status": self.status,
            "error": self.error,
            "created_at": self.created_at,
        }


class CheckpointManager:
    """
    Checkpoint 管理器

    使用方式：
        mgr = CheckpointManager()
        mgr.save(Checkpoint(session_id=..., workflow_type=..., step_name=..., state_snapshot=...))
        last = mgr.get_last_completed(session_id, workflow_type)
        state = mgr.resume_from(session_id, workflow_type, after_step="faq_node")
    """

    _instance: Optional["CheckpointManager"] = None
    _executor: Optional[ThreadPoolExecutor] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        # 扩容到 8：4 workflow × 4-5 步，每次会话 16-20 次写入
        # max_workers=2 在并发下会丢任务（submit 失败时 silently dropped）
        self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="checkpoint")

    def shutdown(self):
        """Graceful shutdown：关闭后台 executor"""
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None

    def save(self, cp: Checkpoint):
        try:
            self._executor.submit(self._do_save, cp)
            _record_checkpoint_metric("save", "submitted")
        except RuntimeError as e:
            # executor 已 shutdown（graceful shutdown 期间）
            logger.warning(f"checkpoint executor 已关闭，fallback 到同步写入: {e}")
            self._do_save(cp)
            _record_checkpoint_metric("save", "shutdown_fallback")
        except Exception as e:
            # 其他 submit 异常（如队列满）—— 至少记一条 log，避免 silently dropped
            logger.warning(f"checkpoint submit 失败: {e} (session={cp.session_id[:8]}, step={cp.step_name})")
            _record_checkpoint_metric("save", "failed")

    def _do_save(self, cp: Checkpoint):
        try:
            pool = get_global_pool()
            if pool is None:
                logger.warning("CheckpointManager: DB pool 不可用，跳过 checkpoint 写入")
                return
            conn = pool.getconn()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO workflow_checkpoints
                        (checkpoint_id, session_id, workflow_type, step_name, state_snapshot, status, error, created_at)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, to_timestamp(%s))
                    ON CONFLICT (session_id, workflow_type, step_name)
                    DO UPDATE SET
                        state_snapshot = EXCLUDED.state_snapshot,
                        status = EXCLUDED.status,
                        error = EXCLUDED.error,
                        created_at = EXCLUDED.created_at,
                        checkpoint_id = EXCLUDED.checkpoint_id
                """, (
                    cp.checkpoint_id,
                    cp.session_id,
                    cp.workflow_type,
                    cp.step_name,
                    json.dumps(cp.state_snapshot, ensure_ascii=False, default=str),
                    cp.status,
                    cp.error,
                    cp.created_at,
                ))
                conn.commit()
                cursor.close()
                _record_step_metric(cp.workflow_type, cp.step_name, cp.status)
                return
            finally:
                pool.putconn(conn)
        except Exception as e:
            logger.error(f"Checkpoint 写入失败: {e}")



    def get(self, session_id: str, workflow_type: str, step_name: str) -> Optional[Checkpoint]:
        try:
            pool = get_global_pool()
            if pool is None:
                return None
            conn = pool.getconn()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT checkpoint_id, state_snapshot, status, error, created_at
                    FROM workflow_checkpoints
                    WHERE session_id = %s AND workflow_type = %s AND step_name = %s
                """, (session_id, workflow_type, step_name))
                row = cursor.fetchone()
                cursor.close()
                if not row:
                    return None
                cp_id, snapshot, status, error, created_at = row
                snapshot = snapshot if isinstance(snapshot, dict) else json.loads(snapshot)
                return Checkpoint(
                    checkpoint_id=cp_id,
                    session_id=session_id,
                    workflow_type=workflow_type,
                    step_name=step_name,
                    state_snapshot=snapshot,
                    status=status,
                    error=error,
                    created_at=created_at.timestamp() if created_at else time.time(),
                )
            finally:
                pool.putconn(conn)
        except Exception as e:
            logger.error(f"Checkpoint 读取失败: {e}")
            return None

    def get_last_completed(self, session_id: str, workflow_type: str) -> Optional[Checkpoint]:
        try:
            pool = get_global_pool()
            if pool is None:
                return None
            conn = pool.getconn()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT checkpoint_id, step_name, state_snapshot, status, error, created_at
                    FROM workflow_checkpoints
                    WHERE session_id = %s
                      AND workflow_type = %s
                      AND status = 'completed'
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (session_id, workflow_type))
                row = cursor.fetchone()
                cursor.close()
                if not row:
                    return None
                cp_id, step_name, snapshot, status, error, created_at = row
                snapshot = snapshot if isinstance(snapshot, dict) else json.loads(snapshot)
                return Checkpoint(
                    checkpoint_id=cp_id,
                    session_id=session_id,
                    workflow_type=workflow_type,
                    step_name=step_name,
                    state_snapshot=snapshot,
                    status=status,
                    error=error,
                    created_at=created_at.timestamp() if created_at else time.time(),
                )
            finally:
                pool.putconn(conn)
        except Exception as e:
            logger.error(f"Checkpoint 查询失败: {e}")
            return None

    def list_steps(self, session_id: str, workflow_type: str) -> List[str]:
        try:
            pool = get_global_pool()
            if pool is None:
                return []
            conn = pool.getconn()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT step_name FROM workflow_checkpoints
                    WHERE session_id = %s AND workflow_type = %s
                    ORDER BY created_at ASC
                """, (session_id, workflow_type))
                result = [row[0] for row in cursor.fetchall()]
                cursor.close()
                return result
            finally:
                pool.putconn(conn)
        except Exception:
            return []

    def list_step_details(self, session_id: str, workflow_type: str) -> List[Dict[str, Any]]:
        """返回结构化 step 详情（step_name/status/created_at），供前端展示。"""
        try:
            pool = get_global_pool()
            if pool is None:
                return []
            conn = pool.getconn()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT step_name, status, created_at FROM workflow_checkpoints
                    WHERE session_id = %s AND workflow_type = %s
                    ORDER BY created_at ASC
                """, (session_id, workflow_type))
                rows = cursor.fetchall()
                cursor.close()
                return [
                    {
                        "step_name": step_name,
                        "status": status,
                        "created_at": created_at.isoformat() if created_at else None,
                    }
                    for step_name, status, created_at in rows
                ]
            finally:
                pool.putconn(conn)
        except Exception:
            return []

    def clear_session(self, session_id: str) -> bool:
        try:
            pool = get_global_pool()
            if pool is None:
                return False
            conn = pool.getconn()
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM workflow_checkpoints WHERE session_id = %s", (session_id,))
                conn.commit()
                cursor.close()
                return True
            finally:
                pool.putconn(conn)
        except Exception as e:
            logger.error(f"Checkpoint 清理失败: {e}")
            return False


def _record_step_metric(workflow_type: str, step_name: str, status: str) -> None:
    """记录 workflow 节点执行次数到 Prometheus"""
    try:
        from app.utils.metrics import workflow_steps_total
        workflow_steps_total.labels(
            workflow_type=workflow_type, step=step_name, status=status,
        ).inc()
    except Exception:
        pass



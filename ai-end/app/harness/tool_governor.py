"""
ToolGovernor —— 工具调用治理

回答"为什么工具调用不会失控"：
1. Sandbox —— 按 Agent 隔离权限，deny by default（无白名单的工具一律拒绝）
2. Rate limiting —— 每个工具每个 session 有最大调用次数（**跨 worker 共享**，走 Redis）
3. Timeout —— 工具调用有超时上限
4. Trace —— 所有调用写入 run_artifacts（事后复盘）

数据流：
    Tool.execute() → ToolGovernor.gate(tool_name, agent, fn) → 沙箱 + 计数 + 限流 + 超时 + 记录

多 worker 说明：
- 旧的 `_call_counts` 是类级 dict，单进程有效，多 uvicorn worker 部署会被绕过
- 现在迁到 Redis：用 INCR + EXPIRE 实现"每 session 每工具 N 次"，跨 worker 生效
- Redis 不可用时降级到内存（单进程场景仍可用）
"""

import json
import logging
import time
import uuid
import threading
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Callable

from app.tools.db import get_global_pool
from app.agents.workflows.constants import WorkflowType
from app.exceptions import ToolCallLimitExceeded, ToolCallTimeout, ToolAccessDenied
from app.config import settings

logger = logging.getLogger(__name__)

# Redis 限流 key 前缀
_RATE_LIMIT_PREFIX = "toolgov:rate:"
_RATE_LIMIT_TTL = 3600  # 1 小时无访问自动过期


@dataclass
class ToolCallRecord:
    """工具调用 trace 记录"""
    session_id: str
    agent: str
    tool_name: str
    arguments: Dict[str, Any]
    result: Any = None
    status: str = "pending"
    error: Optional[str] = None
    latency_ms: float = 0.0
    call_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "call_id": self.call_id,
            "session_id": self.session_id,
            "agent": self.agent,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "status": self.status,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "created_at": self.created_at,
        }


_DEFAULT_LIMITS: Dict[str, int] = {
    "default": 10,
    "vector_search": 5,
    "retrieve_knowledge": 5,
    "get_video_info": 8,
    "query_user_data": 5,
    "recommend_videos": 3,
}


_DEFAULT_TIMEOUT_SECONDS: Dict[str, float] = {
    "default": 30.0,
    "vector_search": 10.0,
    "retrieve_knowledge": 10.0,
    "get_video_info": 5.0,
    "query_user_data": 10.0,
    "recommend_videos": 15.0,
}


class ToolGovernor:
    """
    工具调用治理器

    用法：
        gov = ToolGovernor()
        result = gov.gate(
            session_id="abc",
            agent=WorkflowType.VIDEO_QA,
            tool_name="vector_search",
            arguments={"query": "..."},
            execute_fn=lambda: real_tool(...),
        )

    限流后端：
    - Redis 可用 → INCR 跨 worker 共享（生产部署多 uvicorn worker 必须）
    - Redis 不可用 → 内存 dict 兜底（单进程场景仍可用）
    """

    _instance: Optional["ToolGovernor"] = None
    # 内存兜底（仅 Redis 不可用时使用）
    _call_counts: Dict[str, int] = {}
    _count_timestamps: Dict[str, float] = {}
    _lock: threading.Lock = threading.Lock()
    _executor: Optional[ThreadPoolExecutor] = None
    _artifact_executor: Optional[ThreadPoolExecutor] = None
    _SESSION_TTL_SECONDS: float = 3600.0  # 1 hour
    _CLEANUP_INTERVAL: int = 50
    _call_count_since_cleanup: int = 0

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        # 执行池扩容：之前 max_workers=4，DeepSeek 同步阻塞调用下高并发排队严重
        self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="tool_governor")
        self._artifact_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="artifact")

    def shutdown(self):
        """Graceful shutdown：关闭后台 executor"""
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None
        if self._artifact_executor is not None:
            self._artifact_executor.shutdown(wait=False)
            self._artifact_executor = None

    def _cleanup_stale_sessions(self):
        now = time.time()
        stale_keys = [
            k for k, ts in self._count_timestamps.items()
            if now - ts > self._SESSION_TTL_SECONDS
        ]
        for k in stale_keys:
            self._call_counts.pop(k, None)
            self._count_timestamps.pop(k, None)

    @staticmethod
    def _limit_for(tool_name: str) -> int:
        return _DEFAULT_LIMITS.get(tool_name, _DEFAULT_LIMITS["default"])

    @staticmethod
    def _timeout_for(tool_name: str) -> float:
        return _DEFAULT_TIMEOUT_SECONDS.get(tool_name, _DEFAULT_TIMEOUT_SECONDS["default"])

    def _session_key(self, session_id: str, tool_name: str) -> str:
        return f"{_RATE_LIMIT_PREFIX}{session_id}::{tool_name}"

    def _redis(self):
        """惰性取 Redis 客户端。Redis 不可用时返回 None。"""
        try:
            from app.tools.context_tools import _get_redis
            return _get_redis()
        except Exception:
            return None

    def get_call_count(self, session_id: str, tool_name: str) -> int:
        r = self._redis()
        if r is not None:
            try:
                val = r.get(self._session_key(session_id, tool_name))
                return int(val) if val is not None else 0
            except Exception:
                pass
        # 内存兜底：dict 里存的 key 不带前缀
        with self._lock:
            return self._call_counts.get(f"{session_id}::{tool_name}", 0)

    def reset_session(self, session_id: str):
        """重置 session 的所有工具调用计数（Redis + 内存）"""
        r = self._redis()
        if r is not None:
            try:
                # SCAN 删前缀匹配的 key（避免 KEYS 阻塞）
                pattern = f"{_RATE_LIMIT_PREFIX}{session_id}::*"
                cursor = 0
                while True:
                    cursor, keys = r.scan(cursor=cursor, match=pattern, count=100)
                    if keys:
                        r.delete(*keys)
                    if cursor == 0:
                        break
            except Exception as e:
                logger.debug(f"Redis reset_session 失败: {e}")
        prefix = f"{session_id}::"
        with self._lock:
            for k in list(self._call_counts.keys()):
                if k.startswith(prefix):
                    self._call_counts.pop(k, None)
                    self._count_timestamps.pop(k, None)

    def _incr_count(self, session_id: str, tool_name: str) -> int:
        """
        原子自增计数。返回自增后的值。
        优先 Redis INCR（跨 worker），不可用降级内存。
        """
        r = self._redis()
        key = self._session_key(session_id, tool_name)
        if r is not None:
            try:
                pipe = r.pipeline()
                pipe.incr(key)
                pipe.expire(key, _RATE_LIMIT_TTL)
                results = pipe.execute()
                return int(results[0])
            except Exception as e:
                logger.debug(f"Redis INCR 失败，降级内存: {e}")
        # 内存兜底
        mem_key = f"{session_id}::{tool_name}"
        with self._lock:
            self._call_count_since_cleanup += 1
            if self._call_count_since_cleanup >= self._CLEANUP_INTERVAL:
                self._call_count_since_cleanup = 0
                self._cleanup_stale_sessions()
            self._call_counts[mem_key] = self._call_counts.get(mem_key, 0) + 1
            self._count_timestamps[mem_key] = time.time()
            return self._call_counts[mem_key]

    def _decr_count(self, session_id: str, tool_name: str) -> None:
        """回滚一次自增（用于 INCR 后判定超限的场景）"""
        r = self._redis()
        key = self._session_key(session_id, tool_name)
        if r is not None:
            try:
                # 不能 DECR 到 0 以下：用 Lua 脚本保证原子性，或 pipeline + 检查
                pipe = r.pipeline()
                pipe.decr(key)
                pipe.get(key)
                _, new_val = pipe.execute()
                if new_val is not None and int(new_val) <= 0:
                    r.delete(key)
                return
            except Exception as e:
                logger.debug(f"Redis DECR 失败，降级内存: {e}")
        mem_key = f"{session_id}::{tool_name}"
        with self._lock:
            cur = self._call_counts.get(mem_key, 0)
            if cur <= 1:
                self._call_counts.pop(mem_key, None)
                self._count_timestamps.pop(mem_key, None)
            else:
                self._call_counts[mem_key] = cur - 1

    def gate(
        self,
        session_id: str,
        agent: str,
        tool_name: str,
        arguments: Dict[str, Any],
        execute_fn: Callable[[], Any],
        record_artifact: bool = True,
    ) -> Any:
        """
        治理工具调用：
        0. 沙箱校验（deny by default）—— Agent 无权调用此工具则直接拒绝
        1. 检查调用次数上限
        2. 执行（带超时）
        3. 写入 run_artifacts trace

        沙箱拒绝不会消耗 rate limit 配额（权限问题是分类问题，不是资源问题）。

        HARNESS 关闭时（HARNESS_ENABLED=0）：
        整个 gate 短路为直接调用 execute_fn()——跳过沙箱、限流、超时、trace。
        与 invoke_with_governor 行为一致（应急开关）。
        """
        # HARNESS 关闭：完全短路，不走任何治理
        if not settings.harness_enabled:
            return execute_fn()

        # 0. 沙箱校验（在 rate limit 之前；权限问题独立于配额）
        try:
            from app.tools.tool_registry import ToolSandbox
            if not ToolSandbox.validate_call(tool_name, agent):
                msg = (
                    f"沙箱拒绝: agent '{agent}' 无权调用工具 '{tool_name}' "
                    f"(session={session_id[:8]})"
                )
                logger.warning(msg)
                if record_artifact:
                    self._write_artifact(ToolCallRecord(
                        session_id=session_id, agent=agent, tool_name=tool_name,
                        arguments=arguments, status="rejected_sandbox",
                        error=msg,
                    ))
                raise ToolAccessDenied(tool_name, agent)
        except ToolAccessDenied:
            raise
        except ImportError:
            # tool_registry 不可用时跳过沙箱（兼容旧调用）
            logger.debug("ToolSandbox 不可用，跳过沙箱校验")

        limit = self._limit_for(tool_name)
        # 原子自增（Redis INCR 或内存 +1），超限则回滚
        current = self._incr_count(session_id, tool_name)
        if current > limit:
            # 回滚一次自增（避免占用配额但未执行）
            self._decr_count(session_id, tool_name)
            msg = f"工具 '{tool_name}' 调用超限: {current}/{limit} (session={session_id[:8]})"
            logger.warning(msg)
            if record_artifact:
                self._write_artifact(ToolCallRecord(
                    session_id=session_id, agent=agent, tool_name=tool_name,
                    arguments=arguments, status="rejected",
                    error=msg,
                ))
            raise ToolCallLimitExceeded(tool_name, current, limit)

        record = ToolCallRecord(
            session_id=session_id, agent=agent, tool_name=tool_name,
            arguments=arguments, status="running",
        )

        # Hook：before_tool_call（可拦截）
        try:
            from app.harness.hooks import hooks_manager, HookEvent
            allowed = hooks_manager.trigger_intercept(
                HookEvent.BEFORE_TOOL_CALL,
                session_id=session_id, agent=agent, tool_name=tool_name, arguments=arguments,
            )
            if not allowed:
                logger.warning(f"hook 拦截工具调用: {tool_name} (session={session_id[:8]})")
                record.status = "rejected_hook"
                record.error = "intercepted by before_tool_call hook"
                if record_artifact:
                    self._write_artifact(record)
                return None
        except Exception as e:
            logger.error(f"before_tool_call hook 异常: {e}")

        timeout = self._timeout_for(tool_name)
        start = time.time()
        try:
            future = self._executor.submit(execute_fn)
            try:
                result = future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                future.cancel()
                record.status = "timeout"
                record.error = f"timeout after {timeout}s"
                record.latency_ms = (time.time() - start) * 1000
                if record_artifact:
                    self._write_artifact(record)
                raise ToolCallTimeout(tool_name, timeout)

            record.result = result
            record.status = "success"
            record.latency_ms = (time.time() - start) * 1000
            if record_artifact:
                self._write_artifact(record)
            # Hook：after_tool_call（观察型）
            try:
                hooks_manager.trigger(
                    HookEvent.AFTER_TOOL_CALL,
                    session_id=session_id, agent=agent, tool_name=tool_name,
                    arguments=arguments, result=result,
                )
            except Exception:
                pass
            return result

        except ToolCallLimitExceeded:
            raise
        except ToolAccessDenied:
            raise
        except Exception as e:
            record.status = "error"
            record.error = str(e)
            record.latency_ms = (time.time() - start) * 1000
            if record_artifact:
                self._write_artifact(record)
            raise

    def _write_artifact(self, record: ToolCallRecord):
        try:
            self._artifact_executor.submit(self._do_write_artifact, record)
        except RuntimeError as e:
            logger.warning(f"artifact executor 已关闭: {e}")
        except Exception as e:
            logger.warning(f"artifact submit 失败: {e} (session={record.session_id[:8]})")

    def _do_write_artifact(self, record: ToolCallRecord):
        try:
            pool = get_global_pool()
            if pool is None:
                return
            conn = pool.getconn()
            try:
                cursor = conn.cursor()
                payload = json.dumps(record.to_dict(), ensure_ascii=False, default=str)
                cursor.execute("""
                    INSERT INTO run_artifacts
                        (call_id, session_id, workflow_type, artifact_type, payload, created_at)
                    VALUES (%s, %s, %s, %s, %s::jsonb, to_timestamp(%s))
                """, (
                    record.call_id,
                    record.session_id,
                    record.agent,
                    "tool_call",
                    payload,
                    record.created_at,
                ))
                conn.commit()
                cursor.close()
            finally:
                pool.putconn(conn)
        except Exception as e:
            logger.debug(f"写入 run_artifact 失败（不影响主流程）: {e}")

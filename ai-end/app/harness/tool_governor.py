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

import concurrent.futures
import json
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from app.config import settings
from app.exceptions import ToolAccessDenied, ToolApprovalRequired, ToolCallLimitExceeded, ToolCallTimeout
from app.tools.db import get_global_pool

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
    "search_video_chunks": 5,
    "get_video_info": 8,
    "query_user_data": 5,
    "recommend_videos": 3,
}


_DEFAULT_TIMEOUT_SECONDS: Dict[str, float] = {
    "default": 30.0,
    "vector_search": 10.0,
    "retrieve_knowledge": 10.0,
    "search_video_chunks": 15.0,
    "get_video_info": 5.0,
    "query_user_data": 10.0,
    "recommend_videos": 15.0,
}


def _policy_limits(agent: str, tool_name: str, arguments: Dict[str, Any] = None):
    """声明式 policy 优先，回退硬编码默认值。返回 (max_calls, timeout, decision, max_result_chars, inject_user_id)。"""
    try:
        from app.harness.tool_policy import effective_decision, resolve_rule
        rule = resolve_rule(agent, tool_name)
        decision = effective_decision(rule, arguments)
        return rule.max_calls, rule.timeout_seconds, decision, rule.max_result_chars, rule.inject_user_id
    except Exception:
        return (
            _DEFAULT_LIMITS.get(tool_name, _DEFAULT_LIMITS["default"]),
            _DEFAULT_TIMEOUT_SECONDS.get(tool_name, _DEFAULT_TIMEOUT_SECONDS["default"]),
            "allow",
            4000,
            False,
        )


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
    def _limit_for(tool_name: str, agent: str = "") -> int:
        if agent:
            return _policy_limits(agent, tool_name)[0]
        return _DEFAULT_LIMITS.get(tool_name, _DEFAULT_LIMITS["default"])

    @staticmethod
    def _timeout_for(tool_name: str, agent: str = "") -> float:
        if agent:
            return _policy_limits(agent, tool_name)[1]
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

    def reset_all(self):
        """重置所有 session 的工具调用计数（Redis + 内存）。测试隔离用。"""
        r = self._redis()
        if r is not None:
            try:
                cursor = 0
                while True:
                    cursor, keys = r.scan(cursor=cursor, match=f"{_RATE_LIMIT_PREFIX}*", count=200)
                    if keys:
                        r.delete(*keys)
                    if cursor == 0:
                        break
            except Exception as e:
                logger.debug(f"Redis reset_all 失败: {e}")
        with self._lock:
            self._call_counts.clear()
            self._count_timestamps.clear()

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
        user_id: str = "",
    ) -> Any:
        """
        治理工具调用：
        0. 策略 + 沙箱（deny by default）
        0.5 ask → 无 HITL 时 fail-closed（ToolApprovalRequired）
        0.6 强制注入 user_id（policy.inject_user_id）
        1. 限流
        2. 执行（带超时）
        3. 结果投影（max_result_chars）+ trace
        """
        # HARNESS 关闭：完全短路，不走任何治理
        if not settings.harness_enabled:
            return execute_fn()

        limit, timeout, decision, max_result_chars, inject_uid = _policy_limits(agent, tool_name, arguments)
        if decision == "forbidden":
            msg = f"策略拒绝: agent '{agent}' 禁止调用工具 '{tool_name}'"
            logger.warning(msg)
            try:
                from app.harness.run_trace import trace_event
                trace_event("tool_rejected", tool=tool_name, agent=agent, reason="policy_forbidden")
            except Exception:
                pass
            if record_artifact:
                self._write_artifact(ToolCallRecord(
                    session_id=session_id, agent=agent, tool_name=tool_name,
                    arguments=arguments, status="rejected_policy", error=msg,
                ))
            raise ToolAccessDenied(tool_name, agent)

        if decision == "ask":
            from app.config import settings as _cfg
            if getattr(_cfg, "hitl_enabled", True):
                from app.harness.hitl_approval import (
                    create_approval,
                    is_approved,
                    record_approval,
                    wait_for_decision,
                )

                if is_approved(session_id, agent, tool_name):
                    # 同会话已批准过 → 免重复审批（借鉴 Codex with_cached_approval）
                    try:
                        from app.harness.run_trace import trace_event
                        trace_event("tool_approval_cached", tool=tool_name, agent=agent)
                    except Exception:
                        pass
                    req = None
                    verdict = "approve"
                else:
                    req = create_approval(
                        session_id=session_id,
                        agent=agent,
                        tool_name=tool_name,
                        arguments=arguments,
                    )
                    if record_artifact:
                        self._write_artifact(ToolCallRecord(
                            session_id=session_id, agent=agent, tool_name=tool_name,
                            arguments=arguments, status="needs_approval",
                            error=f"awaiting HITL {req.approval_id}",
                        ))
                    verdict = wait_for_decision(req)
                if verdict == "approve":
                    if req is not None:
                        record_approval(session_id, agent, tool_name)
                    approval_ref = req.approval_id if req else "cached"
                    logger.info(
                        "HITL approved tool=%s agent=%s approval_id=%s",
                        tool_name, agent, approval_ref,
                    )
                    try:
                        from app.harness.run_trace import trace_event
                        trace_event(
                            "tool_approved",
                            tool=tool_name, agent=agent, approval_id=approval_ref,
                        )
                    except Exception:
                        pass
                    # fall through to sandbox / execute
                else:
                    msg = (
                        f"策略要求审批: agent '{agent}' 调用 '{tool_name}' "
                        f"未通过（{verdict}）"
                    )
                    logger.warning(msg)
                    try:
                        from app.harness.run_trace import trace_event
                        trace_event(
                            "tool_rejected",
                            tool=tool_name, agent=agent,
                            reason=f"hitl_{verdict}", approval_id=req.approval_id,
                        )
                    except Exception:
                        pass
                    if record_artifact:
                        self._write_artifact(ToolCallRecord(
                            session_id=session_id, agent=agent, tool_name=tool_name,
                            arguments=arguments, status=f"rejected_hitl_{verdict}", error=msg,
                        ))
                    raise ToolApprovalRequired(tool_name, agent)
            else:
                # 无 HITL：fail-closed
                msg = f"策略要求审批: agent '{agent}' 调用 '{tool_name}' 需人工确认"
                logger.warning(msg)
                try:
                    from app.harness.run_trace import trace_event
                    trace_event("tool_needs_approval", tool=tool_name, agent=agent, reason="policy_ask")
                except Exception:
                    pass
                if record_artifact:
                    self._write_artifact(ToolCallRecord(
                        session_id=session_id, agent=agent, tool_name=tool_name,
                        arguments=arguments, status="needs_approval", error=msg,
                    ))
                raise ToolApprovalRequired(tool_name, agent)

        if inject_uid and user_id:
            from app.harness.tool_projection import inject_tenant_args
            arguments = inject_tenant_args(arguments, user_id=user_id, force_user_id=True)

        try:
            from app.harness.run_trace import trace_event
            trace_event("tool_start", tool=tool_name, agent=agent, arguments=arguments)
        except Exception:
            pass
        try:
            from app.harness.tool_progress import emit_tool_progress
            emit_tool_progress(tool_name, "start")
        except Exception:
            pass

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

        # 原子自增（Redis INCR 或内存 +1），超限则回滚
        current = self._incr_count(session_id, tool_name)
        if current > limit:
            # 回滚一次自增（避免占用配额但未执行）
            self._decr_count(session_id, tool_name)
            msg = f"工具 '{tool_name}' 调用超限: {current}/{limit} (session={session_id[:8]})"
            logger.warning(msg)
            try:
                from app.utils.metrics import rate_limited_requests_total
                rate_limited_requests_total.labels(limiter_name="tool_governor").inc()
            except Exception:
                pass
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
            from app.harness.hooks import HookEvent, hooks_manager
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
        ctx = {"session_id": session_id, "agent": agent, "tool": tool_name, "arguments": arguments}
        try:
            def _execute() -> Any:
                future = self._executor.submit(execute_fn)
                try:
                    return future.result(timeout=timeout)
                except concurrent.futures.TimeoutError:
                    future.cancel()
                    record.status = "timeout"
                    record.error = f"timeout after {timeout}s"
                    record.latency_ms = (time.time() - start) * 1000
                    if record_artifact:
                        self._write_artifact(record)
                    try:
                        from app.harness.tool_progress import emit_tool_progress
                        emit_tool_progress(tool_name, "end", ok=False, duration_ms=record.latency_ms)
                    except Exception:
                        pass
                    raise ToolCallTimeout(tool_name, timeout) from None

            from app.harness.middleware import tool_after, tool_before
            result = tool_before.run(ctx, _execute)

            from app.harness.tool_projection import attach_spill_notice, project_tool_result
            projected = project_tool_result(
                result, max_result_chars, keep=getattr(settings, "tool_result_truncate_keep", "head"),
            )
            # 被截断 → 完整输出落盘 + 追加"完整在哪"提示（字符串/列表/字典通用）
            if projected is not result and getattr(settings, "tool_result_spill_enabled", True):
                try:
                    spill_path = self._spill_full_result(session_id, tool_name, result)
                    projected = attach_spill_notice(projected, spill_path)
                except Exception as e:  # noqa: BLE001
                    logger.debug(f"结果落盘失败（不影响返回）: {e}")
            # tool/after 扩展点：可脱敏/改写返回（默认空链 → 原样）
            projected = tool_after.run({**ctx, "result": projected}, lambda: projected)
            record.result = projected
            record.status = "success"
            record.latency_ms = (time.time() - start) * 1000
            if record_artifact:
                self._write_artifact(record)
            try:
                from app.harness.run_trace import trace_event
                trace_event(
                    "tool_end",
                    tool=tool_name,
                    agent=agent,
                    status="success",
                    latency_ms=record.latency_ms,
                    projected=projected is not result,
                )
            except Exception:
                pass
            try:
                from app.harness.tool_progress import emit_tool_progress
                emit_tool_progress(tool_name, "end", ok=True, duration_ms=record.latency_ms)
            except Exception:
                pass
            # Hook：after_tool_call（观察型）
            try:
                hooks_manager.trigger(
                    HookEvent.AFTER_TOOL_CALL,
                    session_id=session_id, agent=agent, tool_name=tool_name,
                    arguments=arguments, result=projected,
                )
            except Exception:
                pass
            return projected

        except ToolCallLimitExceeded:
            raise
        except ToolAccessDenied:
            raise
        except ToolApprovalRequired:
            raise
        except Exception as e:
            record.status = "error"
            record.error = str(e)
            record.latency_ms = (time.time() - start) * 1000
            if record_artifact:
                self._write_artifact(record)
            try:
                from app.harness.tool_progress import emit_tool_progress
                emit_tool_progress(tool_name, "end", ok=False, duration_ms=record.latency_ms)
            except Exception:
                pass
            raise

    def _spill_full_result(self, session_id: str, tool_name: str, result: Any) -> str:
        """结果被截断时，把**完整输出**落盘，供后续按需读取（借鉴 pi 的 overflow 落盘）。"""
        from app.harness.run_trace import _trace_root

        root = _trace_root() / "tool_outputs"
        root.mkdir(parents=True, exist_ok=True)
        name = f"{(session_id or 'anon')[:16]}_{tool_name}_{int(time.time() * 1000)}.txt"
        path = root / name
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
        path.write_text(text, encoding="utf-8")
        return str(path)

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

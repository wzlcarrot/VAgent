"""HITL 人工审批（借鉴 Claude Code allow/ask/deny）：ask 工具暂停 → 前端确认 → 续跑。"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_pending: Dict[str, "ApprovalRequest"] = {}

# 审批缓存（借鉴 Codex with_cached_approval）：同会话内批准过一次后不再重复问
_APPROVED: Dict[str, float] = {}
_APPROVED_PREFIX = "vagent:hitl_approved:"


def _approval_cache_key(session_id: str, agent: str, tool_name: str) -> str:
    return f"{_APPROVED_PREFIX}{session_id or '-'}:{agent or '-'}:{tool_name}"


def _approval_cache_ttl() -> int:
    return int(getattr(_settings(), "hitl_approval_cache_ttl", 3600))


def _cache_redis():
    try:
        from app.tools.context_tools import _get_redis
        return _get_redis()
    except Exception:
        return None


def record_approval(session_id: str, agent: str, tool_name: str) -> None:
    """记住"该会话已批准该 agent+tool"，后续调用免审批。"""
    ttl = _approval_cache_ttl()
    if ttl <= 0:
        return
    key = _approval_cache_key(session_id, agent, tool_name)
    r = _cache_redis()
    if r is not None:
        try:
            r.set(key, "1", ex=ttl)
            return
        except Exception:
            pass
    with _lock:
        _APPROVED[key] = time.time() + ttl


def is_approved(session_id: str, agent: str, tool_name: str) -> bool:
    ttl = _approval_cache_ttl()
    if ttl <= 0:
        return False
    key = _approval_cache_key(session_id, agent, tool_name)
    r = _cache_redis()
    if r is not None:
        try:
            return bool(r.get(key))
        except Exception:
            pass
    with _lock:
        exp = _APPROVED.get(key)
        if exp is None:
            return False
        if exp > time.time():
            return True
        _APPROVED.pop(key, None)
    return False


@dataclass
class ApprovalRequest:
    approval_id: str
    session_id: str
    agent: str
    tool_name: str
    arguments: Dict[str, Any]
    created_at: float = field(default_factory=time.time)
    timeout_s: float = 60.0
    decision: Optional[str] = None  # approve | deny | timeout
    event: threading.Event = field(default_factory=threading.Event)

    @property
    def pending(self) -> bool:
        return self.decision is None and not self.event.is_set()


def _settings():
    from app.config import settings
    return settings


def create_approval(
    *,
    session_id: str,
    agent: str,
    tool_name: str,
    arguments: Optional[Dict[str, Any]] = None,
    timeout_s: Optional[float] = None,
) -> ApprovalRequest:
    from app.config import settings

    timeout = float(timeout_s if timeout_s is not None else getattr(settings, "hitl_timeout_seconds", 60.0))
    req = ApprovalRequest(
        approval_id=uuid.uuid4().hex[:16],
        session_id=session_id or "",
        agent=agent,
        tool_name=tool_name,
        arguments=dict(arguments or {}),
        timeout_s=max(5.0, min(timeout, 300.0)),
    )
    with _lock:
        _pending[req.approval_id] = req
    return req


def resolve_approval(approval_id: str, decision: str, *, session_id: str = "") -> Dict[str, Any]:
    """用户确认/拒绝。decision: approve | deny"""
    decision = (decision or "").strip().lower()
    if decision not in ("approve", "deny"):
        return {"ok": False, "error": "decision must be approve or deny"}
    with _lock:
        req = _pending.get(approval_id)
        if req is None:
            return {"ok": False, "error": "approval not found or expired"}
        if session_id and req.session_id and session_id != req.session_id:
            return {"ok": False, "error": "session mismatch"}
        if req.decision is not None:
            return {"ok": True, "approval_id": approval_id, "decision": req.decision, "already": True}
        req.decision = decision
        req.event.set()
    return {"ok": True, "approval_id": approval_id, "decision": decision}


def get_approval(approval_id: str) -> Optional[ApprovalRequest]:
    with _lock:
        return _pending.get(approval_id)


def _cleanup(approval_id: str) -> None:
    with _lock:
        _pending.pop(approval_id, None)


def arguments_preview(arguments: Dict[str, Any], max_len: int = 160) -> str:
    try:
        import json
        raw = json.dumps(arguments or {}, ensure_ascii=False, default=str)
    except Exception:
        raw = str(arguments)
    if len(raw) <= max_len:
        return raw
    return raw[: max_len - 1] + "…"


def emit_approval_request(req: ApprovalRequest) -> None:
    """经 tool progress 队列推给 SSE（与 tool/retry 同通道）。"""
    from app.harness.tool_progress import TOOL_DISPLAY_NAMES, _tool_progress_q
    from app.streaming.event_bridge import approval_event

    q = _tool_progress_q.get()
    if q is None:
        return
    payload = approval_event(
        approval_id=req.approval_id,
        tool=req.tool_name,
        label=TOOL_DISPLAY_NAMES.get(req.tool_name, req.tool_name),
        agent=req.agent,
        arguments_preview=arguments_preview(req.arguments),
        timeout_s=req.timeout_s,
    )
    try:
        q.put_nowait(payload)
    except Exception:
        pass


def wait_for_decision(req: ApprovalRequest) -> str:
    """
    阻塞等待用户决策。返回 approve | deny | timeout。
    测试可用 settings.hitl_auto_decision 短路；demo 模式默认 auto-approve。
    """
    import os

    s = _settings()
    auto = getattr(s, "hitl_auto_decision", "") or ""
    auto = str(auto).strip().lower()
    demo = bool(getattr(s, "demo_mode", False)) or os.environ.get("VAGENT_DEMO_MODE", "").lower() in (
        "1", "true", "yes",
    )
    if not auto and demo:
        auto = "approve"
    if auto in ("approve", "deny"):
        req.decision = auto
        req.event.set()
        _cleanup(req.approval_id)
        return auto

    emit_approval_request(req)
    try:
        from app.harness.run_trace import trace_event
        trace_event(
            "tool_needs_approval",
            tool=req.tool_name,
            agent=req.agent,
            approval_id=req.approval_id,
            reason="policy_ask_hitl",
        )
    except Exception:
        pass

    ok = req.event.wait(timeout=req.timeout_s)
    if not ok:
        req.decision = "timeout"
        logger.warning(
            "HITL timeout approval_id=%s tool=%s session=%s",
            req.approval_id, req.tool_name, (req.session_id or "")[:8],
        )
    decision = req.decision or "timeout"
    _cleanup(req.approval_id)
    return decision


def reset_approvals() -> None:
    """测试用。"""
    with _lock:
        for req in _pending.values():
            if req.decision is None:
                req.decision = "deny"
            req.event.set()
        _APPROVED.clear()
        _pending.clear()

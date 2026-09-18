"""SSE 事件桥：统一构造推送给前端的流式事件（借鉴 Ragent AgentStreamEventBridge 契约层）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def status_event(stage: str, label: str) -> Dict[str, Any]:
    return {"type": "status", "stage": stage, "label": label}


def text_event(content: str) -> Dict[str, Any]:
    return {"type": "text", "content": content}


def meta_event(winner_type: str, confidence: float, method: str) -> Dict[str, Any]:
    return {
        "type": "meta",
        "meta": {
            "winner_type": winner_type,
            "confidence": confidence,
            "method": method,
        },
    }


def citations_event(citations: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"type": "citations", "citations": citations}


def videos_event(videos: List[Dict[str, Any]], reasons: List[str]) -> Dict[str, Any]:
    return {"type": "videos", "videos": videos, "reasons": reasons}


def tool_event(
    name: str,
    status: str,
    *,
    label: str = "",
    ok: Optional[bool] = None,
    duration_ms: Optional[float] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "type": "tool",
        "name": name,
        "status": status,
        "label": label or name,
    }
    if ok is not None:
        payload["ok"] = ok
    if duration_ms is not None:
        payload["duration_ms"] = round(float(duration_ms), 1)
    return payload


def harness_event(event_type: str, **payload: Any) -> Dict[str, Any]:
    return {"type": "harness", "event": event_type, "payload": payload}


def retry_event(
    op: str,
    *,
    next_attempt: int,
    max_attempts: int,
    wait_s: float = 0.0,
    status_code: Optional[int] = None,
    error_type: str = "",
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "type": "retry",
        "op": op,
        "next_attempt": next_attempt,
        "max_attempts": max_attempts,
        "wait_s": round(float(wait_s), 2),
    }
    if status_code is not None:
        payload["status_code"] = status_code
    if error_type:
        payload["error_type"] = error_type
    return payload


def approval_event(
    *,
    approval_id: str,
    tool: str,
    label: str = "",
    agent: str = "",
    arguments_preview: str = "",
    timeout_s: float = 60.0,
) -> Dict[str, Any]:
    """HITL：工具策略 ask 时推给前端的审批请求。"""
    return {
        "type": "approval",
        "approval_id": approval_id,
        "tool": tool,
        "label": label or tool,
        "agent": agent,
        "arguments_preview": arguments_preview,
        "timeout_s": round(float(timeout_s), 1),
    }

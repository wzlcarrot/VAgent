"""LLM 重试进度 SSE：retry 发生时推给前端（借鉴 Kimi StepRetry）。"""
from __future__ import annotations

import queue
from contextvars import ContextVar
from typing import Optional

_llm_progress_q: ContextVar[Optional[queue.Queue]] = ContextVar("llm_progress_q", default=None)


def set_llm_progress_queue(q: Optional[queue.Queue]):
    return _llm_progress_q.set(q)


def reset_llm_progress_queue(token) -> None:
    _llm_progress_q.reset(token)


def emit_llm_retry(
    op: str,
    *,
    next_attempt: int,
    max_attempts: int,
    wait_s: float = 0.0,
    status_code: Optional[int] = None,
    error_type: str = "",
) -> None:
    from app.streaming.event_bridge import retry_event

    q = _llm_progress_q.get()
    if q is None:
        return
    payload = retry_event(
        op,
        next_attempt=next_attempt,
        max_attempts=max_attempts,
        wait_s=wait_s,
        status_code=status_code,
        error_type=error_type,
    )
    try:
        q.put_nowait(payload)
    except Exception:
        pass

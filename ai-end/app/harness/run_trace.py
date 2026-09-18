"""
Run Trace —— 有序 JSONL 事件 spine（observe first, interpret later）

热路径只追加事件；离线 scripts/replay_trace.py 再还原 timeline。
"""
from __future__ import annotations

import contextvars
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

_current_run: contextvars.ContextVar[Optional["RunTraceHandle"]] = contextvars.ContextVar(
    "run_trace_handle", default=None
)


@dataclass
class RunTraceHandle:
    session_id: str
    run_id: str
    trace_path: Path
    started_at: float = field(default_factory=time.time)
    _seq: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def emit(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not settings.trace_enabled:
            return {}
        event = {
            "seq": self._next_seq(),
            "ts": time.time(),
            "run_id": self.run_id,
            "session_id": self.session_id,
            "type": event_type,
            "payload": payload or {},
        }
        try:
            line = json.dumps(event, ensure_ascii=False, default=str)
            with self._lock:
                with open(self.trace_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception as e:
            logger.debug(f"run trace write failed: {e}")
        return event

    def _next_seq(self) -> int:
        with self._lock:
            self._seq += 1
            return self._seq


def _trace_root() -> Path:
    root = Path(settings.trace_root)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[2] / root
    root.mkdir(parents=True, exist_ok=True)
    return root


def begin_run(session_id: str, meta: Optional[Dict[str, Any]] = None) -> Optional[RunTraceHandle]:
    if not settings.trace_enabled or not session_id:
        return None
    run_id = uuid.uuid4().hex[:16]
    session_dir = _trace_root() / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    handle = RunTraceHandle(
        session_id=session_id,
        run_id=run_id,
        trace_path=session_dir / f"{run_id}.jsonl",
    )
    _current_run.set(handle)
    handle.emit("run_start", {"meta": meta or {}})
    return handle


def finish_run(status: str = "completed", error: Optional[str] = None) -> None:
    handle = _current_run.get()
    if handle is None:
        return
    handle.emit("run_end", {"status": status, "error": error, "duration_ms": (time.time() - handle.started_at) * 1000})
    _current_run.set(None)


def current_run() -> Optional[RunTraceHandle]:
    return _current_run.get()


def trace_event(event_type: str, **payload: Any) -> Optional[Dict[str, Any]]:
    handle = _current_run.get()
    if handle is None:
        return None
    return handle.emit(event_type, payload)


def read_trace(session_id: str, run_id: str) -> List[Dict[str, Any]]:
    path = _trace_root() / session_id / f"{run_id}.jsonl"
    if not path.exists():
        return []
    events: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def list_runs(session_id: str) -> List[Dict[str, Any]]:
    session_dir = _trace_root() / session_id
    if not session_dir.exists():
        return []
    runs: List[Dict[str, Any]] = []
    for p in sorted(session_dir.glob("*.jsonl"), key=lambda x: x.stat().st_mtime, reverse=True):
        events = read_trace(session_id, p.stem)
        if not events:
            continue
        start = events[0]
        end = events[-1] if events[-1].get("type") == "run_end" else None
        runs.append({
            "run_id": p.stem,
            "started_at": start.get("ts"),
            "status": (end or {}).get("payload", {}).get("status", "unknown"),
            "event_count": len(events),
        })
    return runs


def list_recent_sessions(limit: int = 30) -> List[Dict[str, Any]]:
    """Admin Trace 浏览器：按最近修改时间列出 session。"""
    root = _trace_root()
    if not root.exists():
        return []
    dirs = [p for p in root.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out: List[Dict[str, Any]] = []
    for d in dirs[: max(1, min(limit, 100))]:
        runs = list(d.glob("*.jsonl"))
        out.append({
            "session_id": d.name,
            "run_count": len(runs),
            "mtime": d.stat().st_mtime,
        })
    return out


def summarize_run(session_id: str, run_id: str) -> Dict[str, Any]:
    """Request 级合同摘要：供 admin / 客服对账。"""
    events = read_trace(session_id, run_id)
    if not events:
        return {"session_id": session_id, "run_id": run_id, "found": False}

    tools = []
    retries = []
    guardrails = []
    stop_reason = None
    meta = {}
    status = "unknown"
    duration_ms = None
    for ev in events:
        et = ev.get("type")
        payload = ev.get("payload") or {}
        if et == "run_start":
            meta = payload.get("meta") or {}
        elif et in ("tool_end", "tool_start", "tool_rejected", "tool_needs_approval"):
            tools.append({"type": et, **{k: payload.get(k) for k in ("tool", "agent", "status", "latency_ms", "reason")}})
        elif et == "llm_retry":
            retries.append(payload)
        elif et == "guardrail":
            guardrails.append(payload)
        elif et == "run_end":
            status = payload.get("status", status)
            duration_ms = payload.get("duration_ms")
            stop_reason = payload.get("stop_reason") or stop_reason
        elif et == "supervisor_arbitrate":
            stop_reason = payload.get("winner") or stop_reason

    return {
        "found": True,
        "session_id": session_id,
        "run_id": run_id,
        "status": status,
        "duration_ms": duration_ms,
        "stop_reason": stop_reason,
        "meta": meta,
        "tool_events": tools,
        "llm_retries": retries,
        "guardrails": guardrails,
        "event_count": len(events),
    }

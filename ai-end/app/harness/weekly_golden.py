"""负反馈 → weekly golden 候选集（自动入库，不自动改正式 golden）。"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)
_lock = threading.Lock()


def _golden_root() -> Path:
    root = Path(getattr(settings, "weekly_golden_root", "data/weekly_golden"))
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[2] / root
    root.mkdir(parents=True, exist_ok=True)
    return root


def _week_key(now: Optional[datetime] = None) -> str:
    dt = now or datetime.now(timezone.utc)
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def append_feedback_case(
    *,
    session_id: str,
    user_id: str,
    feedback: str,
    message_index: int,
    question: str = "",
    answer: str = "",
    workflow_type: str = "",
    video_ids: Optional[List[str]] = None,
    reason: str = "",
) -> Dict[str, Any]:
    """
    将反馈写入当周 JSONL。
    - not_helpful：必写（回归候选）
    - helpful：也写，便于正负对照；标记 polarity
    - reason：答偏 / 推不准 / 过时 / 其他
    """
    if not getattr(settings, "weekly_golden_enabled", True):
        return {"written": False, "reason": "disabled"}

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "week": _week_key(),
        "session_id": session_id,
        "user_id": user_id[:16] if user_id else "",
        "feedback": feedback,
        "polarity": "positive" if feedback == "helpful" else "negative",
        "message_index": message_index,
        "question": (question or "")[:500],
        "answer": (answer or "")[:800],
        "workflow_type": workflow_type or "",
        "video_ids": (video_ids or [])[:20],
        "reason": (reason or "")[:64],
        "source": "user_feedback",
    }
    week = record["week"]
    path = _golden_root() / f"{week}.jsonl"
    line = json.dumps(record, ensure_ascii=False)
    with _lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    logger.info("weekly golden append week=%s feedback=%s q=%s", week, feedback, record["question"][:40])
    return {"written": True, "week": week, "path": str(path)}


def list_weekly_cases(week: Optional[str] = None, limit: int = 200) -> Dict[str, Any]:
    week = week or _week_key()
    path = _golden_root() / f"{week}.jsonl"
    cases: List[Dict[str, Any]] = []
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    cases.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    cases = cases[-max(1, min(limit, 1000)) :]
    neg = sum(1 for c in cases if c.get("polarity") == "negative")
    pos = sum(1 for c in cases if c.get("polarity") == "positive")
    return {
        "week": week,
        "path": str(path),
        "count": len(cases),
        "negative": neg,
        "positive": pos,
        "cases": cases,
    }


def list_weeks() -> List[str]:
    root = _golden_root()
    return sorted([p.stem for p in root.glob("*.jsonl")], reverse=True)

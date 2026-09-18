"""推荐点击 → 播放埋点（业务 ROI）。"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)
_lock = threading.Lock()


def _root() -> Path:
    from app.config import settings

    root = Path(getattr(settings, "recommend_click_root", "data/recommend_clicks"))
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[2] / root
    root.mkdir(parents=True, exist_ok=True)
    return root


def _day_key(now: Optional[datetime] = None) -> str:
    dt = now or datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%d")


def record_recommend_click(
    *,
    user_id: str = "",
    video_id: str,
    session_id: str = "",
    source: str = "video_card",
) -> Dict[str, Any]:
    if not (video_id or "").strip():
        return {"written": False, "error": "video_id required"}
    day = _day_key()
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "day": day,
        "user_id": (user_id or "")[:32],
        "video_id": str(video_id)[:64],
        "session_id": (session_id or "")[:64],
        "source": (source or "video_card")[:32],
    }
    path = _root() / f"{day}.jsonl"
    with _lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"written": True, "day": day}


def click_stats(days: int = 7) -> Dict[str, Any]:
    """近 N 天点击统计（含今日）。"""
    days = max(1, min(int(days), 30))
    today = _day_key()
    total = 0
    today_count = 0
    by_day: Dict[str, int] = {}
    root = _root()
    for path in sorted(root.glob("*.jsonl"))[-days:]:
        day = path.stem
        n = 0
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        n += 1
        except Exception as e:
            logger.debug("read click log failed: %s", e)
            continue
        by_day[day] = n
        total += n
        if day == today:
            today_count = n
    return {
        "clicks_today": today_count,
        "clicks_window": total,
        "window_days": days,
        "by_day": by_day,
    }

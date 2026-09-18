"""业务质量看板：运营关心的 7 项核心指标。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from app.config import settings
from app.harness.weekly_golden import _week_key, list_weekly_cases
from app.services.video_indexing import index_stats
from app.tools.db import get_cursor

logger = logging.getLogger(__name__)


def _llm_circuit_snapshot() -> Dict[str, Any]:
    try:
        from app.tools.llm_circuit import get_circuit_status

        return get_circuit_status()
    except Exception as e:
        logger.debug("circuit snapshot failed: %s", e)
        return {"status": "unknown"}


def _stream_permit_snapshot() -> Dict[str, Any]:
    try:
        from app.utils.chat_stream_permit import _GLOBAL_KEY, _redis

        r = _redis()
        global_active = 0
        if r is not None:
            global_active = int(r.get(_GLOBAL_KEY) or 0)
        return {
            "enabled": settings.chat_concurrent_enabled,
            "global_active": global_active,
            "max_global": settings.chat_concurrent_max_global,
        }
    except Exception as e:
        logger.debug("stream permit snapshot failed: %s", e)
        return {"enabled": False, "global_active": 0}


def query_business_quality() -> Dict[str, Any]:
    """聚合 7 项业务指标 + 索引 SLA 摘要。"""
    week = _week_key()
    golden = list_weekly_cases(week=week, limit=500)
    pos = int(golden.get("positive") or 0)
    neg = int(golden.get("negative") or 0)
    fb_total = pos + neg
    helpful_rate = round(pos / fb_total, 4) if fb_total else None

    idx = index_stats()
    circuit = _llm_circuit_snapshot()
    permits = _stream_permit_snapshot()
    try:
        from app.harness.recommend_clicks import click_stats
        clicks = click_stats(days=7)
    except Exception:
        clicks = {"clicks_today": 0, "clicks_window": 0}

    result: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "week": week,
        "db_available": False,
        "metrics": {
            "sessions_today": 0,
            "messages_today": 0,
            "active_users_today": 0,
            "feedback_helpful_rate": helpful_rate,
            "feedback_total_week": fb_total,
            "feedback_positive_week": pos,
            "feedback_negative_week": neg,
            "videos_pending": idx.get("videos_pending", 0),
            "videos_indexed": idx.get("videos_indexed", 0),
            "videos_total": idx.get("videos_total", 0),
            "citations_coverage_7d": None,
            "llm_circuit_state": circuit.get("status", "unknown"),
            "stream_global_active": permits.get("global_active", 0),
            "stream_max_global": permits.get("max_global", 0),
            "recommend_clicks_today": clicks.get("clicks_today", 0),
            "recommend_clicks_7d": clicks.get("clicks_window", 0),
        },
        "index_sla": {
            "pending_sample": idx.get("pending_sample") or [],
            "indexed_ratio": None,
            "pending_alert": bool(idx.get("pending_alert")),
            "pending_alert_threshold": idx.get("pending_alert_threshold"),
        },
    }

    vt = int(idx.get("videos_total") or 0)
    vi = int(idx.get("videos_indexed") or 0)
    if vt > 0:
        result["index_sla"]["indexed_ratio"] = round(vi / vt, 4)

    try:
        with get_cursor() as cursor:
            if cursor is None:
                return result

            result["db_available"] = True

            cursor.execute(
                """
                SELECT COUNT(DISTINCT session_id) AS cnt
                FROM chat_history
                WHERE session_id IS NOT NULL AND created_at >= CURRENT_DATE
                """
            )
            result["metrics"]["sessions_today"] = int((cursor.fetchone() or {}).get("cnt", 0))

            cursor.execute(
                "SELECT COUNT(*) AS cnt FROM chat_history WHERE created_at >= CURRENT_DATE"
            )
            result["metrics"]["messages_today"] = int((cursor.fetchone() or {}).get("cnt", 0))

            cursor.execute(
                """
                SELECT COUNT(DISTINCT user_id) AS cnt
                FROM chat_history
                WHERE user_id IS NOT NULL AND created_at >= CURRENT_DATE
                """
            )
            result["metrics"]["active_users_today"] = int((cursor.fetchone() or {}).get("cnt", 0))

            cursor.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE jsonb_array_length(COALESCE(citations, '[]'::jsonb)) > 0) AS with_cites,
                    COUNT(*) AS total
                FROM chat_history
                WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
                  AND answer IS NOT NULL AND answer <> ''
                """
            )
            row = cursor.fetchone() or {}
            total = int(row.get("total") or 0)
            with_cites = int(row.get("with_cites") or 0)
            if total > 0:
                result["metrics"]["citations_coverage_7d"] = round(with_cites / total, 4)

    except Exception as e:
        logger.error("business quality query failed: %s", e)
        result["error"] = str(e)

    return result

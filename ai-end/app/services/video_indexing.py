"""视频向量索引：上传 → 切块 → embedding → video_vector_block（入库 Pipeline 轻量版）。"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from psycopg2 import errors as pg_errors

from app.tools.db import get_cursor
from app.tools.rag_tools import RAGTools

logger = logging.getLogger(__name__)


def is_video_indexed(video_id: str) -> bool:
    """video_id 在 video_vector_block 中至少有一条 chunk 视为已索引。"""
    if not (video_id or "").strip():
        return False
    try:
        with get_cursor() as cursor:
            if cursor is None:
                return True
            cursor.execute(
                "SELECT 1 FROM video_vector_block WHERE video_id = %s LIMIT 1",
                (video_id.strip(),),
            )
            return cursor.fetchone() is not None
    except pg_errors.UndefinedTable:
        return False


def video_chunk_count(video_id: str) -> int:
    if not (video_id or "").strip():
        return 0
    with get_cursor() as cursor:
        if cursor is None:
            return 0
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM video_vector_block WHERE video_id = %s",
            (video_id.strip(),),
        )
        row = cursor.fetchone()
        return int((row or {}).get("cnt", 0))


def list_pending_video_ids(limit: int = 50) -> List[str]:
    with get_cursor() as cursor:
        if cursor is None:
            return []
        cursor.execute(
            """
            SELECT v.video_id FROM video_info v
            LEFT JOIN video_vector_block b ON v.video_id = b.video_id
            WHERE b.video_id IS NULL
            LIMIT %s
            """,
            (max(1, min(limit, 200)),),
        )
        return [r["video_id"] for r in cursor.fetchall()]


def index_stats() -> Dict[str, Any]:
    from app.config import settings

    stats: Dict[str, Any] = {"db_available": False}
    alert_threshold = max(1, int(getattr(settings, "index_pending_alert_threshold", 10)))
    with get_cursor() as cursor:
        if cursor is None:
            return stats
        stats["db_available"] = True
        cursor.execute("SELECT COUNT(*) AS cnt FROM video_info")
        stats["videos_total"] = (cursor.fetchone() or {}).get("cnt", 0)
        cursor.execute("SELECT COUNT(DISTINCT video_id) AS cnt FROM video_vector_block")
        stats["videos_indexed"] = (cursor.fetchone() or {}).get("cnt", 0)
        cursor.execute("SELECT COUNT(*) AS cnt FROM video_vector_block")
        stats["chunks_total"] = (cursor.fetchone() or {}).get("cnt", 0)
        pending = list_pending_video_ids(limit=200)
        stats["videos_pending"] = len(pending)
        stats["pending_sample"] = pending[:10]
        stats["pending_alert_threshold"] = alert_threshold
        stats["pending_alert"] = len(pending) >= alert_threshold
    return stats


def reindex_pending(limit: int = 50) -> Dict[str, Any]:
    pending = list_pending_video_ids(limit=limit)
    indexed: List[str] = []
    failed: List[Dict[str, str]] = []
    for vid in pending:
        try:
            result = RAGTools.index_video(vid)
            if result.get("success"):
                indexed.append(vid)
            else:
                failed.append({"video_id": vid, "error": result.get("error", "unknown")})
        except Exception as e:
            logger.warning("reindex_pending failed video_id=%s: %s", vid, e)
            failed.append({"video_id": vid, "error": str(e)})
    remaining = list_pending_video_ids(limit=200)
    return {
        "success": True,
        "requested": len(pending),
        "indexed": indexed,
        "indexed_count": len(indexed),
        "failed": failed,
        "pending_remaining": len(remaining),
    }

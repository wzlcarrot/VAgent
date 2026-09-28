"""PostgreSQL：video_subtitle_segment 读写（ASR 原始字幕段，按分片 file 存）。"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.tools.db import get_cursor

logger = logging.getLogger(__name__)


def delete_subtitle_segments(
    video_id: str,
    *,
    file_id: Optional[str] = None,
    file_index: Optional[int] = None,
) -> None:
    vid = (video_id or "").strip()
    if not vid:
        return
    where = "video_id = %s"
    params: List[Any] = [vid]
    if file_id is not None and str(file_id).strip():
        where += " AND file_id = %s"
        params.append(str(file_id).strip())
    elif file_index is not None:
        where += " AND file_index = %s"
        params.append(int(file_index))
    with get_cursor(commit=True) as cursor:
        if cursor is None:
            return
        cursor.execute(f"DELETE FROM video_subtitle_segment WHERE {where}", tuple(params))


def save_subtitle_segments(
    video_id: str,
    segments: List[Dict[str, Any]],
    *,
    file_id: Optional[str] = None,
    file_index: int = 1,
    source: str = "asr",
) -> int:
    """幂等写入：先删该 file 的旧段再插。segments: {text, start_s, end_s?}"""
    vid = (video_id or "").strip()
    if not vid or not segments:
        return 0
    try:
        f_index = int(file_index)
    except (TypeError, ValueError):
        f_index = 1
    f_id = (str(file_id).strip() if file_id else None) or None

    cleaned: List[Dict[str, Any]] = []
    for i, seg in enumerate(segments):
        if not isinstance(seg, dict):
            continue
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        try:
            start_s = float(seg["start_s"])
        except (KeyError, TypeError, ValueError):
            continue
        end_s = seg.get("end_s")
        try:
            end_s = float(end_s) if end_s is not None else None
        except (TypeError, ValueError):
            end_s = None
        cleaned.append({"seq": i, "start_s": start_s, "end_s": end_s, "text": text})

    if not cleaned:
        return 0

    delete_subtitle_segments(vid, file_index=f_index)
    with get_cursor(commit=True) as cursor:
        if cursor is None:
            return 0
        for row in cleaned:
            cursor.execute(
                """
                INSERT INTO video_subtitle_segment
                    (video_id, file_id, file_index, seq, start_s, end_s, text, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (vid, f_id, f_index, row["seq"], row["start_s"], row["end_s"], row["text"], source),
            )
    logger.info(
        "已写入字幕段 video_id=%s file_index=%s count=%d source=%s",
        vid, f_index, len(cleaned), source,
    )
    return len(cleaned)


def load_subtitle_segments(
    video_id: str,
    *,
    file_id: Optional[str] = None,
    file_index: Optional[int] = None,
) -> List[Dict[str, Any]]:
    vid = (video_id or "").strip()
    if not vid:
        return []
    where = "video_id = %s"
    params: List[Any] = [vid]
    if file_id is not None and str(file_id).strip():
        where += " AND file_id = %s"
        params.append(str(file_id).strip())
    elif file_index is not None:
        where += " AND file_index = %s"
        params.append(int(file_index))
    with get_cursor() as cursor:
        if cursor is None:
            return []
        cursor.execute(
            f"""
            SELECT file_id, file_index, seq, start_s, end_s, text, source
            FROM video_subtitle_segment
            WHERE {where}
            ORDER BY file_index, seq
            """,
            tuple(params),
        )
        rows = cursor.fetchall() or []
    out: List[Dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        out.append({
            "file_id": r.get("file_id"),
            "file_index": r.get("file_index"),
            "seq": r.get("seq"),
            "start_s": r.get("start_s"),
            "end_s": r.get("end_s"),
            "text": r.get("text") or "",
            "source": r.get("source") or "asr",
        })
    return out


def subtitle_segment_count(
    video_id: str,
    *,
    file_index: Optional[int] = None,
) -> int:
    vid = (video_id or "").strip()
    if not vid:
        return 0
    where = "video_id = %s"
    params: List[Any] = [vid]
    if file_index is not None:
        where += " AND file_index = %s"
        params.append(int(file_index))
    with get_cursor() as cursor:
        if cursor is None:
            return 0
        cursor.execute(
            f"SELECT COUNT(*) AS cnt FROM video_subtitle_segment WHERE {where}",
            tuple(params),
        )
        row = cursor.fetchone()
    return int((row or {}).get("cnt", 0))

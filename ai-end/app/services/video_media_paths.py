"""解析 ViewHub 视频在磁盘上的路径（与 Java projectFolder + file/ 布局一致）。"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from psycopg2 import errors as pg_errors

from app.config import settings
from app.tools.db import get_cursor

logger = logging.getLogger(__name__)

# 与 easylive Constants.TEMP_VIDEO_NAME 一致
_TEMP_MP4_SUFFIX = "temp.mp4"


def _storage_root() -> Optional[Path]:
    root = (settings.video_storage_root or "").strip()
    if not root:
        return None
    return Path(root).expanduser().resolve()


def list_video_files(video_id: str) -> List[Dict[str, Any]]:
    """video_info_file 行：{file_id, file_index, file_path}（按 file_index 升序）。"""
    vid = (video_id or "").strip()
    if not vid:
        return []
    try:
        with get_cursor() as cursor:
            if cursor is None:
                return []
            cursor.execute(
                """
                SELECT file_id, file_index, file_path
                FROM video_info_file
                WHERE video_id = %s AND file_path IS NOT NULL AND file_path <> ''
                ORDER BY file_index
                """,
                (vid,),
            )
            rows = cursor.fetchall() or []
    except pg_errors.UndefinedTable:
        # Agent-only / CI 库可能只有 init_agent_tables，无 ViewHub 业务表
        return []
    out: List[Dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        rel = str(r.get("file_path") or "").strip().lstrip("/")
        if not rel:
            continue
        try:
            idx = int(r.get("file_index"))
        except (TypeError, ValueError):
            idx = len(out) + 1
        out.append({
            "file_id": (r.get("file_id") or None),
            "file_index": idx,
            "file_path": rel,
        })
    return out


def list_file_paths_for_video(video_id: str) -> List[str]:
    """video_info_file.file_path，如 video/2026/08/02/coverr_BVxxx。"""
    return [f["file_path"] for f in list_video_files(video_id)]


def resolve_media_path_for_file(file_path: str) -> Optional[Path]:
    """把单个 file_path 解析成可转写的本地媒体文件；找不到返回 None。"""
    root = _storage_root()
    if root is None:
        return None
    rel = str(file_path or "").replace("\\", "/").strip("/")
    if not rel:
        return None
    file_root = (root / "file").resolve()
    base = (root / "file" / rel).resolve()
    # 纵深防御：file_path 虽来自 DB 而非用户输入，仍防../穿越逃出媒体根目录
    try:
        base.relative_to(file_root)
    except ValueError:
        logger.warning(f"file_path 越界，已拒绝: {file_path}")
        return None
    candidates: List[Optional[Path]] = [
        base / _TEMP_MP4_SUFFIX,
        base.parent / _TEMP_MP4_SUFFIX if base.suffix else None,
    ]
    if base.is_file():
        candidates.insert(0, base)
    if base.is_dir():
        candidates.extend(sorted(base.glob("*.mp4")))
        candidates.extend(sorted(base.glob("*.m4a")))
        candidates.extend(sorted(base.glob("*.wav")))
        # 转码后 temp.mp4 会被删除，通常只剩 HLS：优先 m3u8（含真实分段顺序），
        # 其次才退化为单个 .ts（仅能覆盖首段，但好过完全找不到）
        hls_playlist = base / "index.m3u8"
        if hls_playlist.is_file() and hls_playlist.stat().st_size > 0:
            candidates.append(hls_playlist)
        candidates.extend(sorted(base.glob("*.ts")))

    for c in candidates:
        if c is None:
            continue
        try:
            if c.is_file() and c.stat().st_size > 0:
                return c.resolve()
        except OSError:
            continue
    return None


def resolve_video_media_path(video_id: str) -> Optional[Path]:
    """
    返回该视频任一可用于 ASR 的本地媒体文件（按 file_index 顺序取第一个命中的）。

    多分片请用 list_video_files + resolve_media_path_for_file 逐片解析。
    """
    root = _storage_root()
    if root is None:
        logger.debug("video_storage_root 未配置，无法解析视频路径 video_id=%s", video_id)
        return None
    for f in list_video_files(video_id):
        p = resolve_media_path_for_file(f["file_path"])
        if p is not None:
            return p
    logger.info("未找到可转写媒体文件 video_id=%s root=%s", video_id, root)
    return None

"""
媒体路由：封面图片代理。

前端 markdown 里的封面 URL 走 /ai/media/cover → 此处。
从 cover_dir 读取真实封面文件（sourceName=cover/xxx 相对路径）；
文件不存在时返回占位 SVG，保证前端图片可显示。
"""
import logging
import os

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from app.config import is_safe_cover_source_name, settings

logger = logging.getLogger(__name__)

router = APIRouter()

_DEFAULT_COVER_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180" width="320" height="180">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#6366F1"/>
      <stop offset="100%" stop-color="#8B5CF6"/>
    </linearGradient>
  </defs>
  <rect width="320" height="180" fill="url(#g)"/>
  <g fill="#fff" opacity="0.9" text-anchor="middle" font-family="system-ui, sans-serif">
    <text x="160" y="82" font-size="22" font-weight="600">视频封面</text>
    <text x="160" y="110" font-size="13" opacity="0.75">ViewHub AI</text>
  </g>
</svg>'''.encode("utf-8")

_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


@router.get("/media/cover")
async def media_cover(sourceName: str = ""):
    """返回封面图：优先读取真实文件，缺失时返回占位封面。"""
    if sourceName:
        if not is_safe_cover_source_name(sourceName):
            return Response(content=_DEFAULT_COVER_SVG, media_type="image/svg+xml")
        # sourceName 形如 cover/2026/08/02/BV1x.jpg → 去 cover/ 前缀
        rel = sourceName.replace("cover/", "", 1)
        cover_root = os.path.abspath(settings.cover_dir)
        path = os.path.abspath(os.path.join(cover_root, rel))
        try:
            inside = os.path.commonpath([cover_root, path]) == cover_root
        except ValueError:
            inside = False
        if not inside:
            return Response(content=_DEFAULT_COVER_SVG, media_type="image/svg+xml")
        if os.path.isfile(path):
            try:
                # 同步文件读放线程池，避免阻塞 event loop
                data = await run_in_threadpool(_read_file, path)
                ext = os.path.splitext(path)[1].lower()
                return Response(content=data, media_type=_CONTENT_TYPES.get(ext, "image/jpeg"))
            except Exception as e:
                logger.warning(f"读取封面失败 {path}: {e}")
    return Response(content=_DEFAULT_COVER_SVG, media_type="image/svg+xml")


def _read_file(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()

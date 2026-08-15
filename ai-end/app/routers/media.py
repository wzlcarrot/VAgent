"""
媒体路由：封面图片代理。

后端容器不含视频封面文件，统一返回占位封面（SVG）。
前端 markdown 里的封面 URL 走 /ai/media/cover → 此处，保证同源、无跨域、无外部视频服务依赖。
"""
import logging
from fastapi import APIRouter
from fastapi.responses import Response

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


@router.get("/media/cover")
async def media_cover(sourceName: str = ""):
    """返回封面图。后端无真实文件时返回占位封面（保证前端图片可显示）。"""
    return Response(content=_DEFAULT_COVER_SVG, media_type="image/svg+xml")

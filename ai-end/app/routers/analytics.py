"""推荐点击埋点路由。"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from app.routers._shared import require_auth

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/analytics/recommend-click")
async def recommend_click(request: Request, authed_user_id: str = Depends(require_auth)):
    try:
        body = await request.json()
    except Exception:
        body = {}
    video_id = str(body.get("video_id") or body.get("videoId") or "").strip()
    if not video_id:
        raise HTTPException(status_code=400, detail="video_id required")
    session_id = str(body.get("session_id") or body.get("sessionId") or "")
    source = str(body.get("source") or "video_card")
    from app.harness.recommend_clicks import record_recommend_click

    result = await run_in_threadpool(
        record_recommend_click,
        user_id=authed_user_id,
        video_id=video_id,
        session_id=session_id,
        source=source,
    )
    if not result.get("written"):
        raise HTTPException(status_code=400, detail=result.get("error") or "failed")
    return {"success": True, **result}

"""HITL 工具审批：前端确认后唤醒等待中的 ToolGovernor。"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from app.routers._shared import require_auth

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/approval/{approval_id}")
async def submit_approval(
    approval_id: str,
    request: Request,
    authed_user_id: str = Depends(require_auth),
):
    """
    审批工具调用。
    Body: { "decision": "approve" | "deny", "session_id": "<optional>" }
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    decision = (body.get("decision") or "").strip().lower()
    session_id = str(body.get("session_id") or body.get("sessionId") or "")

    from app.harness.hitl_approval import resolve_approval

    result = await run_in_threadpool(
        resolve_approval, approval_id, decision, session_id=session_id,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "approval failed")
    logger.info(
        "HITL decision user=%s approval=%s decision=%s",
        (authed_user_id or "")[:8], approval_id, result.get("decision"),
    )
    return result

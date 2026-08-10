"""
反馈路由
"""
import logging
from fastapi import APIRouter, HTTPException, Request, Depends
from app.tools import MemoryTools
from app.routers._shared import require_auth

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/feedback")
async def submit_feedback(request: Request, authed_user_id: str = Depends(require_auth)):
    try:
        body = await request.json()
        user_id = authed_user_id
        if body.get("user_id") and body["user_id"] != authed_user_id:
            logger.warning(f"feedback user_id 不匹配: body={body['user_id']}, token={authed_user_id}，已用 token 覆盖")
        session_id = body.get("session_id")
        message_index = body.get("message_index", 0)
        feedback = body.get("feedback")
        if not all([user_id, session_id, feedback]):
            raise HTTPException(status_code=400, detail="缺少必要参数")
        if feedback not in ("helpful", "not_helpful"):
            raise HTTPException(status_code=400, detail="feedback 必须是 helpful 或 not_helpful")
        if not isinstance(message_index, int) or message_index < 0 or message_index > 1000:
            logger.warning(f"feedback 非法 message_index: {message_index}")
            raise HTTPException(status_code=400, detail="message_index 必须为 0-1000 的整数")
        content = f"用户认为第{message_index + 1}轮回复{'有用' if feedback == 'helpful' else '没用'}"
        from app.agents.workflows import run_sync_in_executor
        await run_sync_in_executor(
            MemoryTools.save_memory,
            user_id=user_id, type="feedback", content=content, source="feedback",
            score=1.0 if feedback == "helpful" else 0.3, tags=[feedback, session_id],
        )
        logger.info(f"反馈已记录 user={user_id} session={session_id} feedback={feedback}")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"提交反馈失败: {e}")
        raise HTTPException(status_code=500, detail="提交反馈失败")

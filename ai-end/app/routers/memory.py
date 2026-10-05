"""用户记忆管理路由：查看 / 删除 AI 对自己的长期记忆。

合规背景：《个人信息保护法》第 47 条，用户有权删除其个人信息；
AI 长期记忆（user_memory：偏好/兴趣/事实）属于个人信息，
必须给用户查看与删除（遗忘）的入口。此前 retract_memory 一直
没有路由暴露，属于死代码。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from app.routers._shared import require_auth
from app.tools import MemoryTools

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_LIST = 100


def _serialize_memory(m) -> dict:
    return {
        "id": m.id,
        "type": m.type,
        "content": m.content,
        "source": m.source,
        "createdAt": m.created_at.isoformat() if m.created_at else None,
    }


@router.get("/memory/list")
async def list_my_memories(request: Request, authed_user_id: str = Depends(require_auth)):
    """列出当前用户的活跃（未被取代/删除）AI 记忆。"""
    memories = await run_in_threadpool(
        MemoryTools.list_active_memories, authed_user_id, _MAX_LIST, False
    )
    return {
        "success": True,
        "total": len(memories),
        "memories": [_serialize_memory(m) for m in memories],
    }


@router.post("/memory/retract")
async def retract_my_memory(request: Request, authed_user_id: str = Depends(require_auth)):
    """遗忘记忆：body 传 {memory_id} 或 {content}；只能删自己的（user_id 强制来自 token）。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    memory_id = body.get("memory_id") or body.get("memoryId")
    content = str(body.get("content") or "").strip()
    if memory_id is None and not content:
        raise HTTPException(status_code=400, detail="需要 memory_id 或 content")
    if memory_id is not None:
        try:
            memory_id = int(memory_id)
        except (TypeError, ValueError) as err:
            raise HTTPException(status_code=400, detail="memory_id 必须是整数") from err
        if memory_id <= 0:
            raise HTTPException(status_code=400, detail="memory_id 非法")

    deleted = await run_in_threadpool(
        MemoryTools.retract_memory, authed_user_id, memory_id, content
    )
    if deleted == 0:
        raise HTTPException(status_code=404, detail="记忆不存在或已删除")
    logger.info("用户遗忘记忆 user=%s count=%s id=%s", authed_user_id[:8], deleted, memory_id)
    return {"success": True, "deleted": deleted}

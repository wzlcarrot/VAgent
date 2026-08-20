"""会话 CRUD / 搜索 / checkpoint 列表。"""
import json as _json
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extras import RealDictCursor

from app.agents.workflows.constants import WorkflowType
from app.routers._shared import require_auth
from app.tools import ChatTools
from app.tools.db import get_global_pool

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/chat/sessions")
async def get_chat_sessions(limit: int = 20, offset: int = 0, authed_user_id: str = Depends(require_auth)):
    try:
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        from app.agents.workflows import run_sync_in_executor
        sessions = await run_sync_in_executor(ChatTools.get_chat_sessions, authed_user_id, limit, offset)
        return {"sessions": sessions}
    except Exception as e:
        logger.error(f"获取会话列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取会话列表失败") from e


@router.get("/chat/history")
async def get_chat_history(session_id: str = None, limit: int = 50, authed_user_id: str = Depends(require_auth)):
    try:
        from app.agents.workflows import run_sync_in_executor
        records = await run_sync_in_executor(ChatTools.get_chat_history, authed_user_id, session_id, limit)
        messages = []
        for r in records:
            videos_val = r.videos
            if isinstance(videos_val, str):
                try:
                    videos_val = _json.loads(videos_val)
                except Exception:
                    videos_val = None
            reasons_val = r.reasons
            if isinstance(reasons_val, str):
                try:
                    reasons_val = _json.loads(reasons_val)
                except Exception:
                    reasons_val = None
            if r.question:
                msg = {
                    "role": "user",
                    "content": r.question,
                    "timestamp": str(r.created_at) if r.created_at else "",
                    "session_id": r.session_id
                }
                if r.image_urls:
                    msg["image_urls"] = r.image_urls
                messages.append(msg)
            if r.answer or videos_val:
                msg = {
                    "role": "assistant",
                    "content": r.answer or "",
                    "timestamp": str(r.created_at) if r.created_at else "",
                    "session_id": r.session_id
                }
                if videos_val:
                    msg["videos"] = videos_val
                if reasons_val:
                    msg["reasons"] = reasons_val
                messages.append(msg)
        messages.sort(key=lambda m: m["timestamp"])
        return {"messages": messages}
    except Exception as e:
        logger.error(f"获取聊天历史失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取聊天历史失败") from e


@router.get("/chat/search")
async def search_chat_content(q: str = "", limit: int = 50, authed_user_id: str = Depends(require_auth)):
    try:
        from app.utils.security import sanitize_search_input
        if not q:
            return {"results": []}
        q = sanitize_search_input(q)
        if not q:
            return {"results": []}
        from app.agents.workflows import run_sync_in_executor
        results = await run_sync_in_executor(search_chat_db, authed_user_id, q, limit)
        return {"results": results}
    except Exception as e:
        logger.error(f"搜索聊天内容失败: {e}")
        return {"results": []}


def search_chat_db(user_id: str, q: str, limit: int) -> List[Dict[str, Any]]:
    from app.utils.security import escape_like_pattern
    pool = get_global_pool()
    if pool is None:
        return []
    conn = pool.getconn()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        like_pattern = f"%{escape_like_pattern(q)}%"
        cursor.execute("""
            SELECT DISTINCT ch.session_id, ch.question, ch.answer, ch.created_at,
                   MIN(ch.created_at) OVER (PARTITION BY ch.session_id) as session_start
            FROM chat_history ch
            WHERE ch.user_id = %s
              AND (ch.question ILIKE %s ESCAPE '\\' OR ch.answer ILIKE %s ESCAPE '\\')
            ORDER BY ch.created_at DESC
            LIMIT %s
        """, (user_id, like_pattern, like_pattern, limit))
        rows = cursor.fetchall()
        cursor.close()
        seen = set()
        results = []
        for r in rows:
            sid = r["session_id"]
            if sid in seen:
                continue
            seen.add(sid)
            snippet = r["answer"] or r["question"] or ""
            idx = snippet.lower().find(q.lower())
            if idx > 0:
                start = max(0, idx - 40)
                end = min(len(snippet), idx + len(q) + 60)
                snippet = ("..." if start > 0 else "") + snippet[start:end] + ("..." if end < len(snippet) else "")
            results.append({
                "session_id": sid,
                "title": (r["question"] or "")[:60],
                "snippet": snippet,
                "matched_in": "question" if q.lower() in (r["question"] or "").lower() else "answer",
                "created_at": str(r.get("created_at") or ""),
            })
        return results[:limit]
    finally:
        pool.putconn(conn)


@router.delete("/chat/session/{session_id}")
async def delete_chat_session(session_id: str, authed_user_id: str = Depends(require_auth)):
    try:
        from app.agents.workflows import run_sync_in_executor
        existing = await run_sync_in_executor(ChatTools.get_chat_history, authed_user_id, session_id, 1)
        if not existing:
            logger.warning(f"删除会话越权拦截: user={authed_user_id} 试图删除 session={session_id}")
            raise HTTPException(status_code=404, detail="会话不存在")
        success = await run_sync_in_executor(ChatTools.delete_chat_session, authed_user_id, session_id)
        return {"success": success}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除会话失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="删除会话失败") from e


def collect_checkpoint_steps(session_id: str) -> List[Dict[str, Any]]:
    from app.harness.checkpoint import CheckpointManager
    mgr = CheckpointManager()
    all_steps = []
    for wf_type in WorkflowType.all():
        steps = mgr.list_step_details(session_id, wf_type)
        if steps:
            last_cp = mgr.get_last_completed(session_id, wf_type)
            all_steps.append({
                "workflow_type": wf_type,
                "steps": steps,
                "last_completed_step": last_cp.step_name if last_cp else None,
                "last_completed_at": last_cp.created_at if last_cp else None,
            })
    return all_steps


@router.get("/chat/checkpoints")
async def get_checkpoints(session_id: str, authed_user_id: str = Depends(require_auth)):
    try:
        from app.agents.workflows import run_sync_in_executor
        owner_check = await run_sync_in_executor(ChatTools.get_chat_history, authed_user_id, session_id, 1)
        if not owner_check:
            logger.warning(f"checkpoints 越权拦截: user={authed_user_id} 试图查 session={session_id}")
            raise HTTPException(status_code=404, detail="会话不存在")
        all_steps = await run_sync_in_executor(collect_checkpoint_steps, session_id)
        return {"session_id": session_id, "checkpoints": all_steps}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 checkpoint 失败: {e}")
        raise HTTPException(status_code=500, detail="获取 checkpoint 失败") from e

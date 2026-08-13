"""
管理统计路由
鉴权：X-Admin-Key header
"""
import logging
import hmac
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from app.config import settings
from app.tools.db import get_cursor

logger = logging.getLogger(__name__)

router = APIRouter()


def _verify_admin_key(request: Request) -> None:
    """校验 X-Admin-Key（fail-closed + 时序安全比较）"""
    expected_key = settings.admin_api_key
    if not expected_key:
        logger.error("admin_api_key 未配置，拒绝访问（fail-closed）")
        raise HTTPException(status_code=503, detail="admin_api_key 未配置")

    provided_key = request.headers.get("X-Admin-Key", "")
    if not hmac.compare_digest(provided_key, expected_key):
        client = request.client.host if request.client else "unknown"
        logger.warning(f"admin 鉴权失败: remote={client}")
        raise HTTPException(status_code=403, detail="Forbidden")


@router.get("/admin/stats")
async def admin_stats(request: Request):
    """系统管理统计（鉴权要求 X-Admin-Key）"""
    _verify_admin_key(request)
    return await run_in_threadpool(_query_stats)


@router.post("/admin/index-video/{video_id}")
async def admin_index_video(video_id: str, request: Request):
    """索引指定视频（Java 上传视频后回调；X-Admin-Key 鉴权）"""
    _verify_admin_key(request)
    from app.tools.rag_tools import RAGTools
    result = await run_in_threadpool(RAGTools.index_video, video_id)
    if not result.get("success"):
        return {**result, "error": result.get("error", "索引失败")}
    return result


def _query_stats() -> dict:
    """同步 DB 统计查询（在 executor 线程执行，避免阻塞 event loop）"""
    stats: dict = {
        "service": settings.app_name,
        "version": "1.0.0",
    }

    try:
        with get_cursor() as cursor:
            if cursor is None:
                return {**stats, "db_available": False, "message": "DB 不可用"}

            cursor.execute("SELECT COUNT(*) as cnt FROM chat_history")
            row = cursor.fetchone()
            stats["total_messages"] = row["cnt"] if row else 0

            cursor.execute("SELECT COUNT(*) as cnt FROM chat_history WHERE created_at >= CURRENT_DATE")
            row = cursor.fetchone()
            stats["messages_today"] = row["cnt"] if row else 0

            cursor.execute(
                "SELECT COUNT(DISTINCT session_id) as cnt FROM chat_history WHERE session_id IS NOT NULL"
            )
            row = cursor.fetchone()
            stats["total_sessions"] = row["cnt"] if row else 0

            cursor.execute("SELECT COUNT(*) as cnt FROM user_memory")
            row = cursor.fetchone()
            stats["total_memories"] = row["cnt"] if row else 0

            cursor.execute("SELECT type, COUNT(*) as cnt FROM user_memory GROUP BY type")
            rows = cursor.fetchall()
            stats["memories_by_type"] = {r["type"]: r["cnt"] for r in (rows or [])}

            cursor.execute(
                "SELECT COUNT(*) as cnt FROM user_memory WHERE type = 'feedback'"
            )
            row = cursor.fetchone()
            stats["feedback_total"] = row["cnt"] if row else 0

            cursor.execute(
                "SELECT COUNT(*) as cnt FROM user_memory WHERE type = 'feedback' AND score >= 1.0"
            )
            row = cursor.fetchone()
            stats["feedback_positive"] = row["cnt"] if row else 0

    except Exception as e:
        logger.error(f"获取统计失败: {e}")
        return {**stats, "db_available": False, "error": str(e)}

    return {**stats, "db_available": True}
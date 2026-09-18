"""
管理统计路由
鉴权：X-Admin-Key header
"""
import hmac
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from app.config import settings
from app.tools.db import get_cursor
from app.tools.rag_tools import RAGTools

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


@router.get("/admin/business-quality")
async def admin_business_quality(request: Request):
    """业务质量看板：7 项核心指标（试点运营 / 答辩用）"""
    _verify_admin_key(request)
    from app.services.business_quality import query_business_quality
    return await run_in_threadpool(query_business_quality)


@router.get("/admin/stats")
async def admin_stats(request: Request):
    """系统管理统计（鉴权要求 X-Admin-Key）"""
    _verify_admin_key(request)
    return await run_in_threadpool(_query_stats)


@router.post("/admin/index-video/{video_id}")
async def admin_index_video(video_id: str, request: Request):
    """索引指定视频（Java 上传视频后回调；X-Admin-Key 鉴权）"""
    _verify_admin_key(request)
    result = await run_in_threadpool(RAGTools.index_video, video_id)
    if not result.get("success"):
        return {**result, "error": result.get("error", "索引失败")}
    return result


@router.get("/admin/index-stats")
async def admin_index_stats(request: Request):
    """入库 Pipeline 状态：已索引/待索引视频与 chunk 数"""
    _verify_admin_key(request)
    from app.services.video_indexing import index_stats
    return await run_in_threadpool(index_stats)


@router.post("/admin/reindex-pending")
async def admin_reindex_pending(request: Request, limit: int = 50):
    """手动触发待索引视频补建（等同启动时 backfill，可运维调用）"""
    _verify_admin_key(request)
    from app.services.video_indexing import reindex_pending
    limit = max(1, min(limit, 200))
    return await run_in_threadpool(reindex_pending, limit)


@router.get("/admin/traces/{session_id}")
async def admin_list_traces(session_id: str, request: Request):
    """按 session 列出 Run Trace（客服对账）"""
    _verify_admin_key(request)
    from app.harness.run_trace import list_runs
    return {"session_id": session_id, "runs": list_runs(session_id)}


@router.get("/admin/trace-sessions")
async def admin_trace_sessions(request: Request, limit: int = 30):
    """最近有 Trace 的 session 列表（Admin Trace 浏览器）"""
    _verify_admin_key(request)
    from app.harness.run_trace import list_recent_sessions
    limit = max(1, min(limit, 100))
    return {"sessions": list_recent_sessions(limit)}


@router.get("/admin/weekly-golden")
async def admin_weekly_golden(request: Request, week: str = "", limit: int = 100):
    """当周反馈入库的 golden 候选"""
    _verify_admin_key(request)
    from app.harness.weekly_golden import list_weekly_cases, list_weeks
    wk = week.strip() or None
    data = list_weekly_cases(wk, limit=limit)
    data["weeks"] = list_weeks()
    return data


@router.get("/admin/traces/{session_id}/{run_id}")
async def admin_get_trace(session_id: str, run_id: str, request: Request, raw: bool = False):
    """查询单次请求 Trace 摘要；raw=1 返回完整事件"""
    _verify_admin_key(request)
    from app.harness.run_trace import read_trace, summarize_run
    if raw:
        return {"session_id": session_id, "run_id": run_id, "events": read_trace(session_id, run_id)}
    summary = summarize_run(session_id, run_id)
    if not summary.get("found"):
        raise HTTPException(status_code=404, detail="trace not found")
    return summary


@router.get("/admin/llm-circuit")
async def admin_llm_circuit(request: Request):
    """LLM 熔断状态"""
    _verify_admin_key(request)
    from app.tools.llm_circuit import get_circuit_status
    return get_circuit_status()


@router.get("/admin/compact-stats")
async def admin_compact_stats(request: Request, session_id: str = ""):
    """会话 Token 压缩统计（按 session 或全局）"""
    _verify_admin_key(request)
    from app.tools.context_tools import get_compact_stats
    sid = session_id.strip() or None
    return {"session_id": sid, "stats": get_compact_stats(sid)}


@router.get("/admin/stream-permits")
async def admin_stream_permits(request: Request):
    """流式并发许可配置与当前占用（Redis 可用时读计数）"""
    _verify_admin_key(request)
    from app.utils.chat_stream_permit import _GLOBAL_KEY, _USER_PREFIX, _redis
    r = _redis()
    global_active = 0
    user_active: dict = {}
    if r is not None:
        try:
            global_active = int(r.get(_GLOBAL_KEY) or 0)
            for key in r.scan_iter(f"{_USER_PREFIX}*"):
                uid = key.replace(_USER_PREFIX, "", 1) if isinstance(key, str) else key.decode().replace(_USER_PREFIX, "", 1)
                user_active[uid] = int(r.get(key) or 0)
        except Exception as e:
            logger.debug("stream permit stats failed: %s", e)
    return {
        "enabled": settings.chat_concurrent_enabled,
        "max_global": settings.chat_concurrent_max_global,
        "max_user": settings.chat_concurrent_max_user,
        "global_active": global_active,
        "user_active": user_active,
    }


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

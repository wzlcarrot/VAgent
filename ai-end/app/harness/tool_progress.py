"""工具调用进度 SSE：workflow 线程内 emit，chat pipeline 侧 drain 后推给前端。"""
from __future__ import annotations

import queue
from contextvars import ContextVar
from typing import Dict, Optional

_tool_progress_q: ContextVar[Optional[queue.Queue]] = ContextVar("tool_progress_q", default=None)

TOOL_DISPLAY_NAMES: Dict[str, str] = {
    "search_video_chunks": "检索视频片段",
    "retrieve_knowledge": "检索知识库",
    "dual_recall_and_rerank": "混合召回",
    "get_video_info": "获取视频信息",
    "recommend_videos": "个性化推荐",
    "get_user_profile": "读取用户画像",
    "get_coin_count": "查询硬币余额",
    "get_followings": "查询关注列表",
    "get_watch_history": "查询观看历史",
}


def set_tool_progress_queue(q: Optional[queue.Queue]):
    return _tool_progress_q.set(q)


def reset_tool_progress_queue(token) -> None:
    _tool_progress_q.reset(token)


def emit_tool_progress(
    tool_name: str,
    status: str,
    *,
    ok: Optional[bool] = None,
    duration_ms: Optional[float] = None,
) -> None:
    from app.streaming.event_bridge import tool_event

    q = _tool_progress_q.get()
    if q is None:
        return
    payload = tool_event(
        tool_name,
        status,
        label=TOOL_DISPLAY_NAMES.get(tool_name, tool_name),
        ok=ok,
        duration_ms=duration_ms,
    )
    try:
        q.put_nowait(payload)
    except Exception:
        pass

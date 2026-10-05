"""校招 / 演示默认路径：开关再多，对外只认这一条。"""
from __future__ import annotations

from typing import Any, Dict


def describe_default_path() -> Dict[str, Any]:
    from app.config import settings

    return {
        "name": "campus_default",
        "story": (
            "一次请求只进一个 LangGraph 工作流；"
            "视频内回答只检索当前视频；"
            "主流程有可展示结果则不再跑闲聊"
        ),
        "orchestration_mode": settings.orchestration_mode,
        "chat_fallback": "sequential",
        "video_qa_uses_web": False,
        "video_asr_enabled": settings.video_asr_enabled,
        "finetune_intent_enabled": settings.finetune_intent_enabled,
        "web_search_for_chat": bool(settings.web_search_enabled),
        "recommend_tool_decision": "allow",
        "lock_default_path": bool(settings.lock_default_path),
        "demo_video_id": settings.demo_video_id,
    }

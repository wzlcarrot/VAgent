"""
多轮对话能力包

- context_manager: 上下文持久化 + 指代消解
- intent_clarifier: 智能追问与澄清
"""
from app.conversation.context_manager import (
    resolve_references,
    get_context_for_query,
    update_recommendations,
    update_video_qa,
    clear_session,
)
from app.conversation.intent_clarifier import IntentClarifier

__all__ = [
    "resolve_references",
    "get_context_for_query",
    "update_recommendations",
    "update_video_qa",
    "clear_session",
    "IntentClarifier",
]
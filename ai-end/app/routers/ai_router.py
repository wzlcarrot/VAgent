"""
AI 路由模块（兼容层）

实际路由已拆分为：
- auth.py      — 登录
- chat.py      — 会话/历史/stream/resume/checkpoints/search
- feedback.py  — 反馈
- admin.py     — 运营统计

共享依赖（token 管理、认证）移至 _shared.py
"""
from app.routers._shared import (
    get_current_user,
    require_auth,
    _token_set,
    _token_get,
    _token_delete,
    start_token_cleanup_task,
    stop_token_cleanup_task,
    TOKEN_TTL,
)
from app.routers import router

__all__ = [
    "router",
    "get_current_user",
    "require_auth",
    "_token_set",
    "_token_get",
    "_token_delete",
    "start_token_cleanup_task",
    "stop_token_cleanup_task",
    "TOKEN_TTL",
]

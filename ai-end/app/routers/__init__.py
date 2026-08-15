from fastapi import APIRouter

from app.routers._shared import start_token_cleanup_task, stop_token_cleanup_task
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.chat import router as chat_router
from app.routers.feedback import router as feedback_router
from app.routers.media import router as media_router

router = APIRouter(prefix="/ai", tags=["ai"])

router.include_router(admin_router)
router.include_router(auth_router)
router.include_router(chat_router)
router.include_router(feedback_router)
router.include_router(media_router)

__all__ = ["router", "start_token_cleanup_task", "stop_token_cleanup_task"]

"""
登录鉴权路由
"""
import logging
import hashlib
import secrets
import time
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse
from app.models import LoginRequest, AuthResponse
from app.routers._shared import require_auth, TEST_ACCOUNT, TOKEN_TTL, _token_set, _clean_expired_tokens
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_test_account():
    """延迟读取配置，避免循环导入"""
    return settings.test_account


@router.post("/login", response_model=AuthResponse)
async def login(request: LoginRequest):
    try:
        password_md5 = hashlib.md5(request.password.encode()).hexdigest()

        _clean_expired_tokens()
        expiry = time.time() + TOKEN_TTL

        test_account = _get_test_account()
        if test_account and request.email == test_account["email"] and password_md5 == test_account["password_md5"]:
            user_id = test_account["user_id"]
            token = secrets.token_urlsafe(32)
            _token_set(token, user_id, expiry)
            return AuthResponse(user={
                "userId": user_id,
                "nickname": test_account["nick_name"],
                "avatar": test_account["avatar"],
                "token": token,
                "tokenExpiresAt": expiry,
            })

        from app.tools import UserTools
        user = UserTools.get_user_by_email(request.email)
        if not user:
            raise HTTPException(status_code=401, detail="邮箱未注册")

        if user.get("password") != password_md5:
            raise HTTPException(status_code=401, detail="密码错误")

        user_id = user.get("user_id")
        token = secrets.token_urlsafe(32)
        _token_set(token, user_id, expiry)
        return AuthResponse(user={
            "userId": user_id,
            "nickname": user.get("nick_name"),
            "avatar": user.get("avatar") or "",
            "token": token,
            "tokenExpiresAt": expiry,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"login error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="登录失败")

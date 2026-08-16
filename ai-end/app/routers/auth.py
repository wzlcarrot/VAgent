"""
登录鉴权路由
"""
import hashlib
import logging
import secrets
import time

import bcrypt
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.config import settings
from app.models import AuthResponse, LoginRequest
from app.routers._shared import AUTH_COOKIE_NAME, TOKEN_TTL, _token_delete, _token_set

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_test_account():
    """延迟读取配置，避免循环导入"""
    return settings.test_account


def _verify_password(plain: str, stored: str) -> bool:
    """bcrypt 优先；兼容旧 MD5 存储（登录成功后由调用方透明升级）"""
    if not stored:
        return False
    if stored.startswith("$2"):
        try:
            return bcrypt.checkpw(plain.encode("utf-8"), stored.encode("utf-8"))
        except ValueError:
            return False
    return hashlib.md5(plain.encode()).hexdigest() == stored


def _auth_cookie_kwargs(expiry: float) -> dict:
    """httpOnly + SameSite=Lax cookie 参数（防 XSS 读取 + CSRF 缓解）"""
    return {
        "key": AUTH_COOKIE_NAME,
        "httponly": True,
        "samesite": "lax",
        "secure": settings.cookie_secure,
        "path": "/",
        "max_age": int(TOKEN_TTL),
        "expires": time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(expiry)),
    }


@router.post("/login")
async def login(request: LoginRequest):
    try:
        expiry = time.time() + TOKEN_TTL

        test_account = _get_test_account()
        if test_account and request.email == test_account["email"] and _verify_password(request.password, test_account["password_md5"]):
            user_id = test_account["user_id"]
            token = secrets.token_urlsafe(32)
            # _token_set 内含同步 Redis 写，放线程池避免阻塞 event loop
            await run_in_threadpool(_token_set, token, user_id, expiry)
            return _login_response(user_id, test_account["nick_name"], test_account["avatar"], token, expiry)

        user = await run_in_threadpool(_get_user_by_email, request.email)
        if not user:
            raise HTTPException(status_code=401, detail="邮箱或密码错误")

        user_id = user.get("user_id")
        stored_password = user.get("password") or ""
        if not _verify_password(request.password, stored_password):
            raise HTTPException(status_code=401, detail="邮箱或密码错误")

        # 透明升级：旧 MD5 密码验证通过后重哈希为 bcrypt
        if not stored_password.startswith("$2"):
            try:
                new_hash = bcrypt.hashpw(request.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                await run_in_threadpool(_upgrade_user_password, user_id, new_hash)
            except Exception as e:
                logger.warning(f"密码哈希升级失败: {e}")

        token = secrets.token_urlsafe(32)
        await run_in_threadpool(_token_set, token, user_id, expiry)
        return _login_response(user_id, user.get("nick_name"), user.get("avatar") or "", token, expiry)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"login error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="登录失败") from e


def _login_response(user_id: str, nickname: str, avatar: str, token: str, expiry: float) -> JSONResponse:
    """返回 AuthResponse JSON + 写入 httpOnly cookie。

    兼容两种客户端：
    - 浏览器：从 cookie 自动鉴权（XSS 不可读 token）
    - 非浏览器（API/测试/工具）：JSON body 里的 token 走 Authorization header
    """
    body = AuthResponse(user={
        "userId": user_id,
        "nickname": nickname,
        "avatar": avatar,
        "token": token,
        "tokenExpiresAt": expiry,
    })
    response = JSONResponse(content=body.model_dump())
    response.set_cookie(**_auth_cookie_kwargs(expiry), value=token)
    return response


@router.post("/logout")
async def logout(request: Request, response: Response):
    """注销：立即失效服务端 token + 清除 httpOnly cookie。

    - 从 cookie / Bearer 读取当前 token 并从内存/Redis 删除（立即失效，不等 TTL）
    - 清 cookie
    """
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else request.cookies.get(AUTH_COOKIE_NAME)
    if token:
        await run_in_threadpool(_token_delete, token)
    response.delete_cookie(
        AUTH_COOKIE_NAME, path="/", httponly=True, samesite="lax", secure=settings.cookie_secure
    )
    return {"success": True}


def _get_user_by_email(email: str):
    from app.tools import UserTools
    return UserTools.get_user_by_email(email)


def _upgrade_user_password(user_id: str, new_hash: str):
    from app.tools import UserTools
    return UserTools.update_user_password(user_id, new_hash)

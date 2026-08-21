"""
登录鉴权路由
"""
import hashlib
import hmac
import logging
import secrets
import threading
import time
from typing import Optional

import bcrypt
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.config import settings
from app.models import AuthResponse, LoginRequest
from app.routers._shared import AUTH_COOKIE_NAME, TOKEN_TTL, _token_delete, _token_set

logger = logging.getLogger(__name__)

router = APIRouter()

# 登录限流：优先 Redis INCR（跨 worker），Redis 不可用时降级内存。
_LOGIN_LIMIT_MAX = 10          # 窗口内最大尝试次数
_LOGIN_LIMIT_WINDOW = 900      # 窗口 15 分钟
_LOGIN_KEY_PREFIX = "login:fail:"
_login_attempts: dict = {}
_login_lock = threading.Lock()


def _login_redis():
    try:
        from app.tools.context_tools import _get_redis
        return _get_redis()
    except Exception:
        return None


def _rate_limited(ip: str) -> bool:
    """返回 True 表示超过限流（应拒绝）。只统计失败次数，成功登录不占配额。"""
    r = _login_redis()
    if r is not None:
        try:
            val = r.get(f"{_LOGIN_KEY_PREFIX}{ip}")
            return int(val or 0) >= _LOGIN_LIMIT_MAX
        except Exception as e:
            logger.debug(f"登录限流读 Redis 失败，降级内存: {e}")
    now = time.time()
    with _login_lock:
        bucket = [t for t in _login_attempts.get(ip, []) if now - t < _LOGIN_LIMIT_WINDOW]
        _login_attempts[ip] = bucket
        return len(bucket) >= _LOGIN_LIMIT_MAX


def _record_login_failure(ip: str) -> None:
    """登录失败时把该 IP 的窗口计数推进一次。"""
    r = _login_redis()
    if r is not None:
        try:
            key = f"{_LOGIN_KEY_PREFIX}{ip}"
            pipe = r.pipeline()
            pipe.incr(key)
            pipe.expire(key, _LOGIN_LIMIT_WINDOW)
            pipe.execute()
            return
        except Exception as e:
            logger.debug(f"登录限流写 Redis 失败，降级内存: {e}")
    now = time.time()
    with _login_lock:
        bucket = _login_attempts.get(ip, [])
        bucket = [t for t in bucket if now - t < _LOGIN_LIMIT_WINDOW]
        bucket.append(now)
        _login_attempts[ip] = bucket


def _clear_login_failures(ip: Optional[str] = None) -> None:
    """测试用：清空限流计数。"""
    r = _login_redis()
    if r is not None:
        try:
            if ip:
                r.delete(f"{_LOGIN_KEY_PREFIX}{ip}")
            else:
                for key in r.scan_iter(f"{_LOGIN_KEY_PREFIX}*"):
                    r.delete(key)
        except Exception:
            pass
    with _login_lock:
        if ip:
            _login_attempts.pop(ip, None)
        else:
            _login_attempts.clear()


def _client_ip(request: Request) -> str:
    if request.client:
        return request.client.host or "unknown"
    return "unknown"


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
    digest = hashlib.md5(plain.encode()).hexdigest()
    if len(digest) != len(stored):
        return False
    return hmac.compare_digest(digest, stored)


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
async def login(request: LoginRequest, req: Request):
    try:
        # 登录限流：按 IP 窗口计数，超限直接 429
        ip = _client_ip(req)
        if _rate_limited(ip):
            logger.warning(f"登录限流触发: ip={ip}")
            try:
                from app.utils.metrics import rate_limited_requests_total
                rate_limited_requests_total.labels(limiter_name="login").inc()
            except Exception:
                pass
            raise HTTPException(status_code=429, detail="尝试过于频繁，请稍后再试")

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
            _record_login_failure(ip)
            raise HTTPException(status_code=401, detail="邮箱或密码错误")

        user_id = user.get("user_id")
        stored_password = user.get("password") or ""
        if not _verify_password(request.password, stored_password):
            _record_login_failure(ip)
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

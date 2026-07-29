"""
共享工具：token 管理、JSON 序列化、认证依赖
"""
import logging
import time
import json
import asyncio
from typing import Dict, Tuple, Optional
from fastapi import Request, HTTPException

try:
    import orjson

    def _json_dumps(obj):
        """orjson 不支持 datetime / 自定义对象，回退到 str()"""
        try:
            return orjson.dumps(obj).decode("utf-8")
        except TypeError:
            return json.dumps(obj, default=str, ensure_ascii=False)
except ImportError:
    def _json_dumps(obj):
        return json.dumps(obj, default=str, ensure_ascii=False)

logger = logging.getLogger(__name__)

# 测试账户从配置读取
TEST_ACCOUNT = None  # 延迟初始化，避免循环导入
TOKEN_TTL = 7 * 24 * 3600

_token_store: Dict[str, Tuple[str, float]] = {}
_token_store_cleanup_counter: int = 0
_TOKEN_STORE_CLEANUP_INTERVAL: int = 100
_token_store_bg_task = None
_token_redis_prefix = "auth:token:"


def _get_token_redis():
    try:
        from app.tools.context_tools import _get_redis
        return _get_redis()
    except Exception as e:
        logger.warning(f"Token Redis 不可用，降级到内存: {e}")
        return None


def _token_set(token: str, user_id: str, expiry: float):
    r = _get_token_redis()
    if r is not None:
        try:
            ttl = max(int(expiry - time.time()), 1)
            r.setex(f"{_token_redis_prefix}{token}", ttl, user_id)
            return
        except Exception as e:
            logger.warning(f"Token 写 Redis 失败，降级到内存: {e}")
    _token_store[token] = (user_id, expiry)
    _maybe_clean_tokens()


def _token_get(token: str) -> Optional[str]:
    r = _get_token_redis()
    if r is not None:
        try:
            return r.get(f"{_token_redis_prefix}{token}")
        except Exception as e:
            logger.warning(f"Token 读 Redis 失败: {e}")
    entry = _token_store.get(token)
    if entry:
        user_id, expiry = entry
        if expiry > time.time():
            return user_id
        _token_store.pop(token, None)
    return None


def _token_delete(token: str):
    r = _get_token_redis()
    if r is not None:
        try:
            r.delete(f"{_token_redis_prefix}{token}")
        except Exception:
            pass
    _token_store.pop(token, None)


def _clean_expired_tokens():
    now = time.time()
    expired = [t for t, (_, exp) in _token_store.items() if exp < now]
    for t in expired:
        del _token_store[t]


def _maybe_clean_tokens():
    global _token_store_cleanup_counter
    _token_store_cleanup_counter += 1
    if _token_store_cleanup_counter >= _TOKEN_STORE_CLEANUP_INTERVAL:
        _token_store_cleanup_counter = 0
        _clean_expired_tokens()


async def _token_store_background_cleanup():
    while True:
        try:
            await asyncio.sleep(300)
            _clean_expired_tokens()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug(f"token_store 后台清理异常: {e}")


def start_token_cleanup_task():
    global _token_store_bg_task
    if _token_store_bg_task is None:
        try:
            loop = asyncio.get_running_loop()
            _token_store_bg_task = loop.create_task(_token_store_background_cleanup())
        except RuntimeError:
            pass


def stop_token_cleanup_task():
    global _token_store_bg_task
    if _token_store_bg_task is not None:
        _token_store_bg_task.cancel()
        _token_store_bg_task = None


def get_current_user(request: Request) -> str:
    """从 Authorization header 解析已认证的 user_id。"""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        user_id = _token_get(token)
        if user_id:
            return user_id
    # 401 时记录指标
    try:
        from app.utils.metrics import auth_failures_total
        reason = "no_token" if not auth else "invalid_or_expired"
        auth_failures_total.labels(reason=reason).inc()
    except Exception:
        pass
    raise HTTPException(status_code=401, detail="未登录或 token 无效")


def require_auth(request: Request) -> str:
    """依赖注入式认证：endpoint 加 Depends(require_auth) 即强制登录。"""
    return get_current_user(request)

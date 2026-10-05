"""聊天流式接口限流（per user_id，内存 + Redis 降级）。"""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, List

logger = logging.getLogger(__name__)

_CHAT_LIMIT_WINDOW = 60
_CHAT_LIMIT_MAX = 30
_CHAT_KEY_PREFIX = "vagent:chat_rl:"
_lock = threading.Lock()
_buckets: Dict[str, List[float]] = {}


def _redis():
    try:
        from app.tools.context_tools import _get_redis
        return _get_redis()
    except Exception:
        return None


def chat_rate_limited(user_id: str) -> bool:
    """True = 超过限流，应拒绝。"""
    if not user_id:
        return False
    r = _redis()
    if r is not None:
        try:
            key = f"{_CHAT_KEY_PREFIX}{user_id}"
            count = int(r.incr(key))
            # 只在窗口开始时设置 TTL。每次 INCR 都 EXPIRE 会把 60 秒窗口不断往后推，
            # 超限后只要还在请求就永远出不了限流。TTL 丢失（expire 曾失败）时再补一次。
            ttl = r.ttl(key)
            if count == 1 or ttl is None or int(ttl) < 0:
                r.expire(key, _CHAT_LIMIT_WINDOW)
            return count > _CHAT_LIMIT_MAX
        except Exception as e:
            logger.debug("chat rate limit redis failed: %s", e)
    now = time.time()
    with _lock:
        bucket = [t for t in _buckets.get(user_id, []) if now - t < _CHAT_LIMIT_WINDOW]
        if len(bucket) >= _CHAT_LIMIT_MAX:
            _buckets[user_id] = bucket
            return True
        bucket.append(now)
        _buckets[user_id] = bucket
        return False


def reset_chat_rate_limit(user_id: str | None = None) -> None:
    """测试用：清空限流计数。"""
    r = _redis()
    if r is not None and user_id:
        try:
            r.delete(f"{_CHAT_KEY_PREFIX}{user_id}")
        except Exception:
            pass
    with _lock:
        if user_id:
            _buckets.pop(user_id, None)
        else:
            _buckets.clear()

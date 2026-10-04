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
            count = r.incr(key)
            # 每次都续期：incr 成功但 expire 偶发失败时，键可能永久无 TTL
            # 导致该用户被永久限流；每次刷新则下次请求即可自愈。
            r.expire(key, _CHAT_LIMIT_WINDOW)
            return int(count) > _CHAT_LIMIT_MAX
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

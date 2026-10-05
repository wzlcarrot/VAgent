"""聊天流式并发许可：Redis Lua 原子抢占 + 持久排队位次（借鉴 Ragent FairDistributedRateLimiter）。"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_LIVE_GLOBAL = "vagent:stream:live:global"
_LIVE_USER_PREFIX = "vagent:stream:live:user:"
_QUEUE_KEY = "vagent:stream:queue"
_TOKEN_PREFIX = "vagent:stream:token:"
_PERMIT_TTL = 600  # 泄漏保护

_lock = threading.Lock()
_mem_global = 0
_mem_user: Dict[str, int] = {}
_mem_token_user: Dict[str, str] = {}

# KEYS: live global zset, live user zset, queue, token
# ARGV: gmax, umax, uid, token, now, ttl
# 许可是带过期时间的成员，不是会一直被续期的计数器。
# 进程拿着许可退出后，成员到点就会被清掉，不会因为别人还在请求就一直累加。
# queue 的 member 用 uid：同一用户只有一个排队位。
# 重试用 ZADD NX，不改原来的入队时间，避免越重试越靠后。
_ACQUIRE_LUA = """
local gkey = KEYS[1]
local ukey = KEYS[2]
local qkey = KEYS[3]
local tkey = KEYS[4]
local gmax = tonumber(ARGV[1])
local umax = tonumber(ARGV[2])
local uid = ARGV[3]
local token = ARGV[4]
local now = tonumber(ARGV[5])
local ttl = tonumber(ARGV[6])
local member = uid
local expiry = now + ttl

redis.call('ZREMRANGEBYSCORE', gkey, '-inf', now)
redis.call('ZREMRANGEBYSCORE', ukey, '-inf', now)

local stale = redis.call('ZRANGEBYSCORE', qkey, '-inf', now - ttl)
if #stale > 0 then
  redis.call('ZREM', qkey, unpack(stale))
end

local g = redis.call('ZCARD', gkey)
local u = redis.call('ZCARD', ukey)
if g < gmax and u < umax then
  redis.call('ZADD', gkey, expiry, token)
  redis.call('ZADD', ukey, expiry, token)
  redis.call('EXPIRE', gkey, ttl)
  redis.call('EXPIRE', ukey, ttl)
  redis.call('SETEX', tkey, ttl, uid)
  redis.call('ZREM', qkey, member)
  return {1, 0, 0}
end

redis.call('ZADD', qkey, 'NX', now, member)
redis.call('EXPIRE', qkey, ttl)
local rank = redis.call('ZRANK', qkey, member)
local pos = (rank or 0) + 1
local retry = math.min(30, 2 + pos * 0.5)
return {0, pos, retry}
"""

# 释放只删这一条流的 token。排队成员是用户 id，同一用户可能还在等下一次重试，
# 这里不能按用户 id 删排队记录。拿到许可时 acquire 会自己移出队列。
_RELEASE_LUA = """
local gkey = KEYS[1]
local ukey = KEYS[2]
local tkey = KEYS[3]
local token = ARGV[1]

redis.call('ZREM', gkey, token)
redis.call('ZREM', ukey, token)
redis.call('DEL', tkey)
return 1
"""


@dataclass
class StreamPermit:
    acquired: bool
    token: str = ""
    queue_position: int = 0
    retry_after_seconds: float = 0.0
    reason: str = ""


def _redis():
    try:
        from app.tools.context_tools import _get_redis
        return _get_redis()
    except Exception:
        return None


def _limits() -> Tuple[int, int]:
    from app.config import settings
    return (
        max(1, getattr(settings, "chat_concurrent_max_global", 100)),
        max(1, getattr(settings, "chat_concurrent_max_user", 3)),
    )


def try_acquire_stream_permit(user_id: str) -> StreamPermit:
    """原子获取流式许可；失败时返回持久排队位次与建议重试间隔。"""
    from app.config import settings

    if not getattr(settings, "chat_concurrent_enabled", True):
        return StreamPermit(acquired=True, token=str(uuid.uuid4()))

    global_max, user_max = _limits()
    token = str(uuid.uuid4())
    uid = user_id or "anon"
    r = _redis()

    if r is not None:
        try:
            res = r.eval(
                _ACQUIRE_LUA,
                4,
                _LIVE_GLOBAL,
                f"{_LIVE_USER_PREFIX}{uid}",
                _QUEUE_KEY,
                f"{_TOKEN_PREFIX}{token}",
                global_max,
                user_max,
                uid,
                token,
                time.time(),
                _PERMIT_TTL,
            )
            acquired = int(res[0]) == 1
            if acquired:
                return StreamPermit(acquired=True, token=token)
            pos = int(res[1] or 1)
            retry = float(res[2] or min(30.0, 2.0 + pos * 0.5))
            try:
                g = int(r.zcard(_LIVE_GLOBAL) or 0)
            except (TypeError, ValueError):
                g = 0
            reason = "global_busy" if g >= global_max else "user_busy"
            return StreamPermit(
                acquired=False,
                token=token,
                queue_position=pos,
                retry_after_seconds=retry,
                reason=reason,
            )
        except Exception as e:
            logger.debug("stream permit redis lua failed: %s", e)

    # 内存降级
    global _mem_global
    with _lock:
        u = _mem_user.get(uid, 0)
        if _mem_global >= global_max or u >= user_max:
            pos = max(_mem_global - global_max + 1, u - user_max + 1, 1)
            return StreamPermit(
                acquired=False,
                token=token,
                queue_position=pos,
                retry_after_seconds=min(30.0, 2.0 + pos * 0.5),
                reason="memory_limit",
            )
        _mem_global += 1
        _mem_user[uid] = u + 1
        _mem_token_user[token] = uid
    return StreamPermit(acquired=True, token=token)


def release_stream_permit(token: str, user_id: Optional[str] = None) -> None:
    if not token:
        return
    r = _redis()
    if r is not None:
        try:
            tkey = f"{_TOKEN_PREFIX}{token}"
            uid = user_id
            if not uid:
                raw = r.get(tkey)
                if raw is None:
                    # 可能仅在排队 ZSET 中（未拿到许可）
                    uid = "anon"
                else:
                    uid = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
            r.eval(
                _RELEASE_LUA,
                3,
                _LIVE_GLOBAL,
                f"{_LIVE_USER_PREFIX}{uid}",
                tkey,
                token,
            )
            return
        except Exception as e:
            logger.debug("release stream permit redis failed: %s", e)

    global _mem_global
    with _lock:
        mapped_uid = _mem_token_user.pop(token, None)
        if mapped_uid is None:
            # token 不是本进程内存模式颁发的（Redis 模式颁发 / 重复释放），
            # 不做递减，防止计数往"更松"方向漂移
            return
        uid = user_id or mapped_uid
        _mem_global = max(0, _mem_global - 1)
        if uid in _mem_user:
            _mem_user[uid] = max(0, _mem_user[uid] - 1)
            if _mem_user[uid] == 0:
                _mem_user.pop(uid, None)


def reset_stream_permits() -> None:
    """测试用：清空许可计数。"""
    global _mem_global
    r = _redis()
    if r is not None:
        try:
            for key in r.scan_iter("vagent:stream:*"):
                r.delete(key)
        except Exception:
            pass
    with _lock:
        _mem_global = 0
        _mem_user.clear()
        _mem_token_user.clear()

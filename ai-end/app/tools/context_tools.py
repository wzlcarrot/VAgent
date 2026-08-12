import json
import logging
import threading
import time
from typing import List, Dict, Optional
from app.config import settings

logger = logging.getLogger(__name__)

_redis_client = None
_redis_lock = threading.Lock()
_compact_stats_lock = threading.Lock()
_compact_stats = {}
_compact_lock = threading.Lock()
_MAX_COMPACT_STATS = 1000

# Redis 熔断器：防止 Redis 短暂不可用时每个请求都尝试重连
_REDIS_COOLDOWN_SECONDS = settings.redis_cooldown_seconds
_last_redis_failure: float = 0.0
_redis_circuit_open: bool = False

_COMPACT_TOKEN_THRESHOLD = settings.compact_token_threshold
_COMPACT_COOLDOWN_SECONDS = settings.compact_cooldown_seconds


def _get_redis():
    """获取 Redis 客户端（带熔断器，防止重连风暴）"""
    global _redis_client, _last_redis_failure, _redis_circuit_open
    now = time.time()

    # 快速路径：熔断器开启中，直接返回 None
    with _redis_lock:
        if _redis_circuit_open and (now - _last_redis_failure) < _REDIS_COOLDOWN_SECONDS:
            return None
        client = _redis_client

    if client is not None:
        try:
            client.ping()
            return client
        except Exception:
            with _redis_lock:
                if _redis_client is client:
                    try:
                        client.disconnect()
                    except Exception:
                        pass
                    _redis_client = None
                    _last_redis_failure = now
                    _redis_circuit_open = True
            logger.warning(f"Redis 探活失败，开启熔断器（{_REDIS_COOLDOWN_SECONDS}s 内不重连）")
            return None

    with _redis_lock:
        # double-check: another thread may have connected while we were outside the lock
        if _redis_client is not None:
            return _redis_client
        try:
            import redis
            new_client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                db=settings.redis_db,
                password=settings.redis_password or None,
                decode_responses=True,
                socket_timeout=2,
                socket_connect_timeout=2,
            )
            new_client.ping()
            _redis_client = new_client
            _redis_circuit_open = False
            _last_redis_failure = 0.0
            logger.info("Redis 连接成功")
            return _redis_client
        except Exception as e:
            _last_redis_failure = now
            _redis_circuit_open = True
            logger.warning(f"Redis 不可用，开启熔断器（{_REDIS_COOLDOWN_SECONDS}s 内不重连）: {e}")
            return None


def _messages_key(session_id: str) -> str:
    return f"session:{session_id}:messages"


def _summary_key(session_id: str) -> str:
    return f"session:{session_id}:summary"


def save_message(session_id: str, role: str, content: str) -> bool:
    client = _get_redis()
    if not client:
        return False
    try:
        msg = json.dumps({"role": role, "content": content})
        key = _messages_key(session_id)
        client.rpush(key, msg)
        client.expire(key, settings.context_ttl)
        return True
    except Exception as e:
        logger.error(f"Redis 保存消息失败: {e}")
        return False


def get_recent_messages(session_id: str, limit: int = None) -> List[Dict[str, str]]:
    client = _get_redis()
    if not client:
        return []
    try:
        limit = limit or settings.context_max_rounds
        key = _messages_key(session_id)
        raw = client.lrange(key, -limit * 2, -1)
        messages = []
        for r in raw:
            try:
                messages.append(json.loads(r))
            except json.JSONDecodeError:
                continue
        return messages
    except Exception as e:
        logger.error(f"Redis 获取消息失败: {e}")
        return []


def get_summarized_context(session_id: str) -> str:
    client = _get_redis()
    if not client:
        return ""
    try:
        key = _summary_key(session_id)
        summary = client.get(key)
        return summary or ""
    except Exception as e:
        logger.error(f"Redis 获取摘要失败: {e}")
        return ""


def update_summary(session_id: str, summary: str) -> bool:
    client = _get_redis()
    if not client:
        return False
    try:
        key = _summary_key(session_id)
        client.setex(key, settings.context_summary_ttl, summary)
        return True
    except Exception as e:
        logger.error(f"Redis 更新摘要失败: {e}")
        return False


def build_context(session_id: str) -> List[Dict[str, str]]:
    client = _get_redis()
    if not client:
        return []

    key = _messages_key(session_id)
    raw = client.lrange(key, -settings.context_max_rounds * 6, -1)
    messages = []
    for r in raw:
        try:
            messages.append(json.loads(r))
        except json.JSONDecodeError:
            continue

    from app.tools.compact_service import is_compact_boundary, is_compact_summary
    from app.tools.message_models import COMPACT_SUMMARY_FLAG

    context = []
    summary_found = False

    for msg in messages:
        content = msg.get("content", "")
        role = msg.get("role", "")

        if is_compact_boundary(msg):
            continue

        if is_compact_summary(msg):
            summary_text = content.replace(f"[{COMPACT_SUMMARY_FLAG}]", "").strip()
            if summary_text:
                context.append({
                    "role": "system",
                    "content": f"【历史对话摘要】\n{summary_text}"
                })
                summary_found = True
            continue

        if role == "user" or role == "assistant":
            context.append(msg)

    if not summary_found:
        legacy_summary = get_summarized_context(session_id)
        if legacy_summary:
            context.insert(0, {
                "role": "system",
                "content": f"【历史对话摘要】\n{legacy_summary}"
            })

    return context


_compact_in_progress = set()


def _estimate_tokens_for_sample(raw_messages: list, total_count: int) -> int:
    """
    估算 session 总 token 数。

    优先 tiktoken（精确），不可用时按字符估算：
    - 中文 ~0.7 token/char（1 token ≈ 1.5 汉字）
    - 英文 ~0.25 token/char（1 token ≈ 4 字符）
    - 混合按 0.5 取均值
    """
    if not raw_messages or total_count <= 0:
        return 0
    sample_size = len(raw_messages)

    # 优先 tiktoken
    try:
        from app.tools.compact_service import count_tokens
        per_msg_tokens = []
        for raw in raw_messages:
            try:
                msg = json.loads(raw)
                content = msg.get("content", "")
                if isinstance(content, str) and content:
                    per_msg_tokens.append(count_tokens(content))
                elif isinstance(content, list):
                    parts = []
                    for blk in content:
                        if isinstance(blk, dict) and blk.get("text"):
                            parts.append(blk["text"])
                    if parts:
                        per_msg_tokens.append(count_tokens("\n".join(parts)))
            except (json.JSONDecodeError, ValueError):
                continue
        if per_msg_tokens:
            avg = sum(per_msg_tokens) / len(per_msg_tokens)
            return int(avg * total_count)
    except Exception:
        pass

    # 退化：字符估算（区分中英文，统一走 token_estimation 的 rough 估算）
    from app.tools.token_estimation import rough_token_count
    total_tokens = 0
    for raw in raw_messages:
        try:
            msg = json.loads(raw)
            content = msg.get("content", "")
            if isinstance(content, str):
                total_tokens += rough_token_count(content)
            elif isinstance(content, list):
                for blk in content:
                    if isinstance(blk, dict) and blk.get("text"):
                        total_tokens += rough_token_count(blk["text"])
        except (json.JSONDecodeError, ValueError):
            continue
    avg = total_tokens / max(sample_size, 1)
    return int(avg * total_count)


def _compact_probe(session_id: str) -> Optional[tuple]:
    """
    同步 Redis 探活：返回是否需要压缩。
    全部在 executor 线程执行，避免阻塞 event loop。
    需要压缩时返回 (client, cooldown_key)，否则返回 None。
    """
    client = _get_redis()
    if not client:
        return None

    key = _messages_key(session_id)
    try:
        msg_count = client.llen(key)
    except Exception:
        return None
    if msg_count <= settings.context_max_rounds * 3:
        return None

    cooldown_key = f"session:{session_id}:last_compact"
    try:
        last_ts = client.get(cooldown_key)
        if last_ts and (time.time() - float(last_ts)) < _COMPACT_COOLDOWN_SECONDS:
            return None
    except Exception:
        pass

    try:
        raw_sample = client.lrange(key, 0, min(10, msg_count - 1))
        # 优先用 tiktoken 算（compact_service 已加载 gpt-4 tokenizer）
        # tiktoken 不可用时按中文字符估算（中文 ~0.7 token/char）
        estimated_tokens = _estimate_tokens_for_sample(raw_sample, msg_count)
        if estimated_tokens < _COMPACT_TOKEN_THRESHOLD:
            return None
    except Exception as e:
        logger.debug(f"Token 估算失败，跳过阈值检查: {e}")

    return (client, cooldown_key)


async def async_summarize_context(session_id: str):
    import asyncio
    with _compact_lock:
        if session_id in _compact_in_progress:
            return
        _compact_in_progress.add(session_id)

    def _release():
        with _compact_lock:
            _compact_in_progress.discard(session_id)

    loop = asyncio.get_running_loop()
    probe = await loop.run_in_executor(None, _compact_probe, session_id)
    if probe is None:
        _release()
        return

    try:
        from app.tools.compact_service import compact_conversation
        result = await compact_conversation(session_id)
        if result.get("success"):
            with _compact_stats_lock:
                if len(_compact_stats) >= _MAX_COMPACT_STATS:
                    oldest_keys = sorted(
                        _compact_stats,
                        key=lambda k: _compact_stats[k].get("total_compacts", 0)
                    )[:_MAX_COMPACT_STATS // 4]
                    for k in oldest_keys:
                        _compact_stats.pop(k, None)
                session_stats = _compact_stats.get(session_id, {
                    "total_compacts": 0, "total_tokens_saved": 0, "history": []
                })
                session_stats["total_compacts"] += 1
                session_stats["total_tokens_saved"] += result["tokens_saved"]
                session_stats["history"].append({
                    "round": session_stats["total_compacts"],
                    "tokens_saved": result["tokens_saved"],
                    "pre_tokens": result["pre_tokens"],
                    "post_tokens": result["post_tokens"],
                })
                _compact_stats[session_id] = session_stats
            logger.info(
                f"Compact完成 | session={session_id[:8]}... "
                f"tokens: {result['pre_tokens']}→{result['post_tokens']} "
                f"节省: {result['tokens_saved']} "
                f"消息: {result['pre_count']}→{result['post_count']}"
            )
            client, cooldown_key = probe
            await loop.run_in_executor(
                None,
                lambda: client.setex(cooldown_key, _COMPACT_COOLDOWN_SECONDS, str(time.time())),
            )
    except Exception as e:
        logger.warning(f"Compact失败: {e}")
    finally:
        _release()

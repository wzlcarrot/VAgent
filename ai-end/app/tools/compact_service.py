"""
Compact对话压缩服务

三重压缩策略：
1. Microcompact预处理 - 清理冗余消息、合并连续同角色消息
2. LLM结构化摘要 - 按意图/关键信息/待办生成摘要
3. 边界标记增量替换 - 标记已压缩区域，保留最新对话
"""

import asyncio
import json
import logging
from typing import List, Dict, Tuple
from app.config import settings
from app.tools.message_models import Message

logger = logging.getLogger(__name__)
COMPACT_PROMPT_TEMPLATE = """
总结以下对话历史的核心内容。

要求：
1. 用户核心需求：用户问了什么
2. 关键信息：讨论了哪些内容
3. 已完成的回答：助手已经回复了什么
4. 待办事项：还有哪些未完成的需求

200字以内，保留关键信息。

对话历史：
{history}
"""


def microcompact_messages(messages: List[Dict]) -> Tuple[List[Dict], int]:
    """
    第一步：Microcompact预处理
    - 清理空消息
    - 合并连续同角色消息（user/assistant/system 都会合并）
    - 去除冗余系统提示
    """
    if not messages:
        return [], 0

    original_count = len(messages)
    cleaned = []

    for msg in messages:
        m = Message.from_dict(msg) if isinstance(msg, dict) else msg
        content = m.content
        role = m.role

        if role == "assistant" and not content:
            continue
        if role == "system" and not content:
            continue

        cleaned.append(m)

    merged = []
    for msg in cleaned:
        if merged and merged[-1].role == msg.role:
            prev = merged[-1]
            # 字符串 content 直接拼；list content（多模态）只保留第一个，后续丢弃避免重复
            if isinstance(prev.content, str) and isinstance(msg.content, str):
                separator = "\n"
                prev.content = (prev.content + separator + msg.content) if prev.content else msg.content
                continue
            # 字符串 + list：不合并（避免破坏多模态结构）
        merged.append(msg)

    result = [m.to_dict() for m in merged]
    saved = original_count - len(result)
    return result, saved


def create_compact_boundary(trigger: str = "auto") -> Dict:
    """compact 边界标记：用 is_internal 结构化字段替代字符串 flag。"""
    return Message(
        role="system",
        content=f"trigger={trigger}",
        is_internal=True,
    ).to_dict()


def create_compact_summary(summary_text: str) -> Dict:
    """compact 摘要标记：is_internal 结构化字段。"""
    return Message(
        role="system",
        content=summary_text,
        is_internal=True,
    ).to_dict()


def is_compact_boundary(msg: Dict) -> bool:
    """兼容式识别：is_internal 字段 或 旧字符串 flag。"""
    m = Message.from_dict(msg) if isinstance(msg, dict) else msg
    return m.is_compact_boundary


def is_compact_summary(msg: Dict) -> bool:
    """兼容式识别：is_internal 字段 或 旧字符串 flag。"""
    m = Message.from_dict(msg) if isinstance(msg, dict) else msg
    return m.is_compact_summary


def warmup_tokenizer() -> bool:
    """启动期预热 tiktoken（委托 token_estimation 的编码器）。失败不抛异常。"""
    try:
        from app.tools.token_estimation import warmup as _warmup_estimation
        ok = _warmup_estimation()
        logger.info("tiktoken 预热完成" if ok else "tiktoken 预热失败（将使用字符估算回退）")
        return ok
    except Exception as e:
        logger.warning(f"tiktoken 预热失败: {e}")
        return False


def count_tokens(text: str) -> int:
    """统计 token 数。委托 token_estimation（tiktoken 精估 + 中英区分回退）。"""
    from app.tools.token_estimation import count_tokens as _est
    return _est(text)


def count_messages_tokens(messages: List[Dict]) -> int:
    """按消息结构估算 token 总数（含 role 开销）。委托 token_estimation。"""
    from app.tools.token_estimation import count_messages_tokens as _est
    return _est(messages)


async def compact_conversation(session_id: str) -> Dict:
    """
    执行对话压缩
    返回压缩结果统计
    """
    from app.tools.llm_tools import LLM_tools
    from app.tools.context_tools import _get_redis, _messages_key

    loop = asyncio.get_running_loop()

    def _read_redis():
        client = _get_redis()
        if not client:
            return None
        key = _messages_key(session_id)
        raw = client.lrange(key, 0, -1)
        return client, key, raw

    read_result = await loop.run_in_executor(None, _read_redis)
    if read_result is None:
        return {"success": False, "reason": "Redis不可用"}

    client, key, raw = read_result
    if not raw or len(raw) < 4:
        return {"success": False, "reason": "消息太少"}

    all_messages = []
    for r in raw:
        try:
            all_messages.append(json.loads(r))
        except json.JSONDecodeError:
            continue

    recent_count = settings.context_max_rounds * 2
    old_messages = all_messages[:-recent_count] if len(all_messages) > recent_count else []
    recent_messages = all_messages[-recent_count:] if len(all_messages) > recent_count else all_messages

    if not old_messages:
        return {"success": False, "reason": "无需压缩"}

    if any(is_compact_boundary(m) for m in old_messages):
        return {"success": False, "reason": "已有压缩边界"}

    pre_count = len(old_messages)
    pre_tokens = count_messages_tokens(old_messages)

    compacted_old, micro_saved = microcompact_messages(old_messages)

    history_text = "\n".join([
        f"{m['role']}: {m['content'][:300]}"
        for m in compacted_old
        if isinstance(m.get("content"), str) and m.get("content")
    ])

    if not history_text:
        return {"success": False, "reason": "无有效历史内容"}

    prompt = COMPACT_PROMPT_TEMPLATE.format(history=history_text)

    messages_for_llm = [
        {"role": "system", "content": "你是一个对话压缩助手。"},
        {"role": "user", "content": prompt},
    ]

    summary_text = ""
    summary_usage = None
    loop = asyncio.get_running_loop()
    for attempt in range(2):
        try:
            # 用 chat_sync_with_usage 拿到 LLM 真实 usage，精确统计摘要 token（借鉴 kimi-cli compaction）
            result = await loop.run_in_executor(
                None, lambda: LLM_tools.chat_sync_with_usage(messages_for_llm, temperature=0.3)
            )
            if result and result[0]:
                summary_text = result[0].strip()
                summary_usage = result[1]
                break
        except Exception as e:
            logger.warning(f"Compact摘要尝试{attempt+1}失败: {e}")

    if not summary_text:
        summary_text = _fallback_summary(compacted_old)

    new_messages = []
    new_messages.append(create_compact_boundary())
    new_messages.append(create_compact_summary(summary_text))
    new_messages.extend(compacted_old)
    new_messages.extend(recent_messages)

    try:
        def _write_redis():
            pipe = client.pipeline(transaction=True)
            pipe.delete(key)
            for msg in new_messages:
                pipe.rpush(key, json.dumps(msg))
            pipe.expire(key, settings.context_ttl)
            pipe.execute()
        await loop.run_in_executor(None, _write_redis)
    except Exception as e:
        logger.error(f"Compact写回Redis失败: {e}")
        _record_compact_metric("failed")
        return {"success": False, "reason": f"写回失败: {e}"}

    post_count = len(new_messages)
    post_tokens = count_messages_tokens(new_messages)
    # 借鉴 kimi-cli compaction：摘要用 LLM 真实 usage.completion_tokens 精确计数，
    # 替代估算（估算值仍保留在返回里供对比）
    summary_tokens_exact = None
    if summary_usage and summary_usage.get("completion_tokens"):
        summary_tokens_exact = summary_usage["completion_tokens"]
        # 用精确摘要 token 替换估算中的摘要消息部分
        # 估算含 role 开销(+4)，精确值只含 content，需补回 role 开销
        from app.tools.token_estimation import MESSAGE_ROLE_OVERHEAD
        summary_estimated = count_tokens(summary_text) + MESSAGE_ROLE_OVERHEAD
        post_tokens = max(0, post_tokens - summary_estimated) + summary_tokens_exact + MESSAGE_ROLE_OVERHEAD
    tokens_saved = pre_tokens - post_tokens

    _record_compact_metric("success")
    _record_compact_tokens_saved(max(0, tokens_saved))

    return {
        "success": True,
        "pre_count": pre_count,
        "post_count": post_count,
        "pre_tokens": pre_tokens,
        "post_tokens": post_tokens,
        "tokens_saved": max(0, tokens_saved),
        "micro_saved": micro_saved,
        "summary_length": len(summary_text),
        "summary_tokens_exact": summary_tokens_exact,
        "summary_usage": summary_usage,
    }


def _record_compact_metric(status: str) -> None:
    """记录 compact 操作到 Prometheus"""
    try:
        from app.utils.metrics import compact_operations_total
        compact_operations_total.labels(status=status).inc()
    except Exception:
        pass


def _record_compact_tokens_saved(saved: int) -> None:
    """记录 compact 节省的 token 数"""
    if saved <= 0:
        return
    try:
        from app.utils.metrics import compact_tokens_saved_total
        compact_tokens_saved_total.inc(saved)
    except Exception:
        pass


def _fallback_summary(messages: List[Dict]) -> str:
    user_msgs = []
    assistant_msgs = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "user" and isinstance(content, str):
            user_msgs.append(content[:200])
        elif role == "assistant" and isinstance(content, str):
            assistant_msgs.append(content[:200])

    parts = [f"对话共 {len(messages)} 条。"]
    if user_msgs:
        parts.append(f"用户主要询问：{user_msgs[-1][:100]}")
    if assistant_msgs:
        parts.append(f"助手已回复：{len(assistant_msgs)} 轮")

    return "\n".join(parts)

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

logger = logging.getLogger(__name__)

_TOKENIZER = None
COMPACT_BOUNDARY_FLAG = "__compact_boundary__"
COMPACT_SUMMARY_FLAG = "__compact_summary__"
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
        content = msg.get("content", "")
        role = msg.get("role", "")

        if role == "assistant" and not content:
            continue
        if role == "system" and not content:
            continue

        cleaned.append(msg)

    merged = []
    for msg in cleaned:
        if merged and merged[-1]["role"] == msg["role"]:
            prev = merged[-1]
            # 字符串 content 直接拼；list content（多模态）只保留第一个，后续丢弃避免重复
            if isinstance(prev["content"], str) and isinstance(msg["content"], str):
                separator = "\n"
                prev["content"] = (prev["content"] + separator + msg["content"]) if prev["content"] else msg["content"]
                continue
            # 字符串 + list：不合并（避免破坏多模态结构）
        merged.append(msg)

    saved = original_count - len(merged)
    return merged, saved


def create_compact_boundary(trigger: str = "auto") -> Dict:
    return {
        "role": "system",
        "content": f"[{COMPACT_BOUNDARY_FLAG}] trigger={trigger}",
    }


def create_compact_summary(summary_text: str) -> Dict:
    return {
        "role": "system",
        "content": f"[{COMPACT_SUMMARY_FLAG}]\n{summary_text}",
    }


def is_compact_boundary(msg: Dict) -> bool:
    return COMPACT_BOUNDARY_FLAG in msg.get("content", "")


def is_compact_summary(msg: Dict) -> bool:
    return COMPACT_SUMMARY_FLAG in msg.get("content", "")


def warmup_tokenizer() -> bool:
    """启动期预热 tiktoken（首次加载需下载 vocab，1-3s）。失败不抛异常。"""
    global _TOKENIZER
    if _TOKENIZER is not None:
        return True
    try:
        import tiktoken
        _TOKENIZER = tiktoken.encoding_for_model("gpt-4")
        logger.info("tiktoken 预热完成")
        return True
    except Exception as e:
        logger.warning(f"tiktoken 预热失败: {e}")
        _TOKENIZER = None
        return False


def count_tokens(text: str) -> int:
    """统计 token 数。优先用 tiktoken（精确），降级到字符长度估算。"""
    global _TOKENIZER
    if _TOKENIZER is None:
        # 惰性初始化（首次访问才加载）
        warmup_tokenizer()
    if _TOKENIZER is not None:
        try:
            return len(_TOKENIZER.encode(text))
        except Exception:
            pass
    return len(text)


def count_messages_tokens(messages: List[Dict]) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += count_tokens(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("text"):
                    total += count_tokens(block["text"])
    return total


async def compact_conversation(session_id: str) -> Dict:
    """
    执行对话压缩
    返回压缩结果统计
    """
    from app.tools.llm_tools import LLM_tools
    from app.tools.context_tools import _get_redis, _messages_key

    client = _get_redis()
    if not client:
        return {"success": False, "reason": "Redis不可用"}

    key = _messages_key(session_id)
    raw = client.lrange(key, 0, -1)
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
    loop = asyncio.get_running_loop()
    for attempt in range(2):
        try:
            result = await loop.run_in_executor(
                None, lambda: LLM_tools.chat_sync(messages_for_llm, temperature=0.3)
            )
            if result:
                summary_text = result.strip()
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
        pipe = client.pipeline(transaction=True)
        pipe.delete(key)
        for msg in new_messages:
            pipe.rpush(key, json.dumps(msg))
        pipe.expire(key, settings.context_ttl)
        pipe.execute()
    except Exception as e:
        logger.error(f"Compact写回Redis失败: {e}")
        _record_compact_metric("failed")
        return {"success": False, "reason": f"写回失败: {e}"}

    post_count = len(new_messages)
    post_tokens = count_messages_tokens(new_messages)
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

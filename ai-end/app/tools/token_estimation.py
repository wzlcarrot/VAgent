"""
分层 token 估算工具

参考 Clawd-Codex 的 token_estimation.py 设计，适配 VAgent 的消息结构。

层级：
- count_tokens: 精确估算（tiktoken cl100k_base），回退中英区分字符估算
- rough_token_count: 粗估（中英区分，不走 tiktoken），用于 compact 预检触发，避免每次开销
- count_messages_tokens: 按消息结构估算（role 开销 + content 精估 + 多模态块权重）

估算口径：
- 中文字符 ≈ 0.7 token/char（1 token ≈ 1.5 汉字）
- 英文字符 ≈ 0.25 token/char（1 token ≈ 4 字符）
- role 开销 +4/条（对齐 Claude/OpenAI 的 per-message overhead）
- image/document 块按固定权重（预留未来多模态消息）
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 多模态块 token 权重（预留：当前 VAgent 消息为纯文本，图片在 image_urls 字段）
IMAGE_BLOCK_TOKENS = 500
DOCUMENT_BLOCK_TOKENS = 2000
# 每条消息的 role 开销（role token + 结构开销）
MESSAGE_ROLE_OVERHEAD = 4

_ENCODER_CACHE: Optional[Any] = None


def _load_tiktoken() -> Optional[Any]:
    """加载 tiktoken 编码器，不可用时返回 None。"""
    global _ENCODER_CACHE
    if _ENCODER_CACHE is not None:
        return _ENCODER_CACHE
    try:
        import tiktoken
        _ENCODER_CACHE = tiktoken.get_encoding("cl100k_base")
    except Exception:
        _ENCODER_CACHE = None
    return _ENCODER_CACHE


def count_tokens(text: str) -> int:
    """精确估算 token 数。优先 tiktoken，回退中英区分字符估算。"""
    if not text:
        return 0
    encoder = _load_tiktoken()
    if encoder is not None:
        try:
            return len(encoder.encode(text))
        except Exception:
            pass
    return rough_token_count(text)


def rough_token_count(text: str) -> int:
    """粗估 token 数（中英区分，不走 tiktoken）。用于预检/快速触发判断。"""
    if not text:
        return 0
    cn = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    en = len(text) - cn
    return max(1, int(cn * 0.7 + en * 0.25))


def _count_block(block: Any) -> int:
    """估算单个 content block 的 token 数。"""
    if not isinstance(block, dict):
        return rough_token_count(str(block))
    block_type = block.get("type", "")
    if block_type == "text":
        return count_tokens(block.get("text", ""))
    if block_type == "image":
        return IMAGE_BLOCK_TOKENS
    if block_type == "document":
        return DOCUMENT_BLOCK_TOKENS
    if block_type in ("tool_use", "tool_result"):
        name = block.get("name", "")
        input_ = block.get("input", {})
        return count_tokens(name) + rough_token_count(str(input_))
    return rough_token_count(str(block))


def count_messages_tokens(messages: List[Dict]) -> int:
    """按消息结构估算 token 总数（含 role 开销与多模态块权重）。"""
    total = 0
    for msg in messages:
        total += MESSAGE_ROLE_OVERHEAD
        content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
        if isinstance(content, str):
            total += count_tokens(content)
        elif isinstance(content, list):
            for block in content:
                total += _count_block(block)
    return total


def warmup() -> bool:
    """启动期预热 tiktoken 编码器（首次加载需下载 vocab）。失败不抛异常。"""
    if _load_tiktoken() is not None:
        return True
    return False

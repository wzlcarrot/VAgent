"""
记忆合并（Consolidation）。

当单用户活跃记忆过多时，与其粗暴淘汰，不如让 LLM 把**相关/冗余**的记忆
合并成更概括的少数几条（如「喜欢科幻」「喜欢《沙丘》」「喜欢太空题材」→「喜欢科幻/太空题材」）。

借鉴 ragent 的 `AgentMemoryConsolidator`：超容量前先尝试合并。

注意：合并必须**无损或近似无损**——不能把不同偏好硬合。合一失败（LLM 不可用/解析失败）
就返回空列表，调用方保持原记忆不动（宁可保留，不可丢信息）。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_CONSOLIDATE_SYSTEM = """你是用户长期记忆的合并器。

给定一批用户记忆，把**表达同一主题/可归并**的条目合并成更概括的少数几条；
无法合并的保持独立。**绝不丢失信息、绝不把不同的事实硬合**。

只输出 JSON：{"items": [{"type": "preference|activity|fact", "content": "..."}]}
要求：
- 合并后条目数应**少于**输入（能合才合，不能合就原样保留）
- 每条 content 仍是关于用户的、自包含的一句话
- 只输出 JSON，不要解释
"""


def _parse(raw: str) -> List[Dict[str, str]]:
    text = (raw or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return []
    items = obj.get("items")
    if not isinstance(items, list):
        return []
    out: List[Dict[str, str]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        content = str(it.get("content") or "").strip()
        if content:
            out.append({"type": str(it.get("type") or "preference"), "content": content})
    return out


def consolidate_memories(items: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """把一批记忆合并成更少的条目；失败返回 []（调用方保持原样）。"""
    items = [i for i in (items or []) if (i.get("content") or "").strip()]
    if len(items) < 2:
        return []

    try:
        from app.harness.llm_replay import replay_enabled, replay_memory_consolidate

        if replay_enabled():
            replayed = replay_memory_consolidate(items)
            if replayed is not None:
                return _parse(replayed)
    except Exception:
        pass

    listing = "\n".join(
        f"[{i + 1}] ({it.get('type', 'preference')}) {it.get('content')}" for i, it in enumerate(items)
    )
    try:
        from app.tools.llm_tools import LLM_tools

        raw = LLM_tools.chat_sync(
            [
                {"role": "system", "content": _CONSOLIDATE_SYSTEM},
                {"role": "user", "content": f"待合并记忆：\n{listing}"},
            ],
            temperature=0.0,
            max_tokens=500,
        ) or ""
        merged = _parse(raw)
        if merged and len(merged) < len(items):
            return merged
        return []
    except Exception as e:  # noqa: BLE001
        logger.debug("记忆合并失败: %s", e)
        return []

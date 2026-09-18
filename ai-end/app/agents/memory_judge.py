"""
记忆冲突判定（记忆写入前的 LLM Judge）。

借鉴 ragent 的 `AgentMemoryJudge`：写入新记忆前，让独立 LLM 对比
「已有有效记忆」与「新提取的记忆」，输出决策 ADD / SUPERSEDE / NOOP。

为什么不用相似度：
    pg_trgm / embedding 对「同结构不同语义」无能为力——
    「用户喜欢咖啡」vs「用户喜欢茶」、「用户喝咖啡」vs「用户不喝咖啡」
    词面/向量都高度相似，但语义不同。只有 LLM 能处理否定与同义改写。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ACTIONS = ("ADD", "SUPERSEDE", "NOOP")

_JUDGE_SYSTEM = """你是用户长期记忆的冲突判定器。

给定【已有记忆】（带 id）和【新记忆】，判断二者关系，只输出一行 JSON：
- 新记忆与某条已有记忆表达**同一事实/偏好**（含同义改写、含新记忆更新旧信息）→
  {"action":"SUPERSEDE","target_id":<已有记忆id>}
- 新记忆是**全新信息**（与任何已有记忆不冲突）→ {"action":"ADD","target_id":null}
- 新记忆已被已有记忆**完全覆盖**、无需新增 → {"action":"NOOP","target_id":null}

注意：
- 「喜欢咖啡」和「喜欢茶」是**不同**偏好，不是同一条。
- 「喜欢咖啡」和「不喝咖啡」是**冲突**，新记忆应 SUPERSEDE 旧的。
- 只输出 JSON，不要解释。
"""


@dataclass
class MemoryDecision:
    action: str = "ADD"          # ADD | SUPERSEDE | NOOP
    target_id: Optional[int] = None
    source: str = "llm"          # replay | llm | fallback


def _parse(raw: str) -> Optional[MemoryDecision]:
    text = (raw or "").strip()
    if not text:
        return None
    # 容错：截取第一个 { ... }
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    action = str(obj.get("action", "")).upper()
    if action not in ACTIONS:
        return None
    target = obj.get("target_id")
    try:
        target_id = int(target) if target is not None else None
    except (TypeError, ValueError):
        target_id = None
    if action == "SUPERSEDE" and target_id is None:
        return None
    return MemoryDecision(action=action, target_id=target_id)


def judge_memory(
    new_content: str,
    existing: List[Dict[str, Any]],
    *,
    memory_type: str = "preference",
) -> MemoryDecision:
    """判定新记忆与已有记忆的关系。不可用时 fail-safe 到 ADD（只增不改）。"""
    new_content = (new_content or "").strip()
    if not new_content:
        return MemoryDecision(action="NOOP", source="fallback")

    try:
        from app.harness.llm_replay import replay_enabled, replay_memory_judge

        if replay_enabled():
            replayed = replay_memory_judge(new_content, existing)
            if replayed is not None:
                d = _parse(replayed)
                if d:
                    d.source = "replay"
                    return d
    except Exception:
        pass

    existing_text = "\n".join(
        f"[{m.get('id')}] ({m.get('type', 'preference')}) {m.get('content', '')}"
        for m in (existing or [])
    ) or "（无）"
    try:
        from app.tools.llm_tools import LLM_tools

        messages = [
            {"role": "system", "content": _JUDGE_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"【已有记忆】\n{existing_text}\n\n"
                    f"【新记忆】({memory_type}) {new_content}"
                ),
            },
        ]
        raw = LLM_tools.chat_sync(messages, temperature=0.0, max_tokens=64) or ""
        decision = _parse(raw)
        if decision:
            logger.info("memory judge: action=%s target=%s", decision.action, decision.target_id)
            return decision
    except Exception as e:  # noqa: BLE001
        logger.debug("memory judge failed: %s", e)

    return MemoryDecision(action="ADD", source="fallback")

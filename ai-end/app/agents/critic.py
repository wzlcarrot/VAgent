"""
独立评审 Agent（Reflection / Critique）。

与 Corrective 的区别：
- Corrective（verify_answer_grounded）在同一流程里对证据片段做启发式/短 LLM 判定；
- Critic 独立成"另一个大脑"：只接收 问题 + 回答 + 证据，看不到生成过程与 ReAct 轨迹，
  从"是否回答问题、是否有幻觉、是否完整"三个维度独立评审，避免自评放水。

多智能体范式里最难被替代的价值就是"独立验证"，本模块即该范式的落地。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List

from app.config import settings

logger = logging.getLogger(__name__)

_CRITIC_SYSTEM = """你是独立的回答质量评审员，与生成回答的助手没有任何共享上下文。
只依据下面给出的【证据】评审【回答】。你没有看到生成过程，也不要假设回答一定正确。

评审三个维度：
1. 是否正面回答了用户问题
2. 关键事实是否都能在证据中找到（无幻觉）
3. 是否完整（没有遗漏问题要求的要点）

只输出一行：
- 通过：OK
- 不通过：PROBLEM: <最严重的一个问题，20 字内>
"""


@dataclass
class CritiqueResult:
    ok: bool
    issue: str = ""
    source: str = "disabled"  # replay | llm | disabled | error
    raw: str = ""


def _evidence_text(evidence: List[Dict[str, Any]], max_items: int = 4, max_len: int = 200) -> str:
    parts: List[str] = []
    for item in evidence or []:
        if not isinstance(item, dict):
            continue
        text = (item.get("content") or item.get("block_content") or "").strip()
        if text:
            parts.append(f"[{len(parts) + 1}] {text[:max_len]}")
        if len(parts) >= max_items:
            break
    return "\n".join(parts)


def _parse_verdict(raw: str) -> tuple[bool, str]:
    text = (raw or "").strip()
    low = text.lower()
    if low.startswith("ok") or "通过" in text:
        return True, ""
    if "problem" in low or "不通过" in text:
        issue = text.split(":", 1)[1].strip() if ":" in text else text
        return False, issue[:40]
    # 解析不出结论时 fail-open：不阻塞回答，仅记录
    return True, ""


def critique_answer(
    question: str,
    answer: str,
    evidence: List[Dict[str, Any]],
    *,
    video_id: str = "",
) -> CritiqueResult:
    """独立评审回答；不可用时 fail-open（返回 ok=True）。"""
    if not settings.video_qa_critic_enabled:
        return CritiqueResult(ok=True, source="disabled")
    if not (answer or "").strip():
        return CritiqueResult(ok=False, issue="empty_answer", source="llm")

    try:
        from app.harness.llm_replay import replay_critique, replay_enabled

        if replay_enabled():
            replayed = replay_critique(question, answer, _evidence_text(evidence))
            if replayed is not None:
                ok, issue = _parse_verdict(replayed)
                return CritiqueResult(ok=ok, issue=issue, source="replay", raw=replayed)
    except Exception:
        pass

    try:
        from app.tools.llm_tools import LLM_tools

        messages = [
            {"role": "system", "content": _CRITIC_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"【用户问题】\n{question}\n\n"
                    f"【回答】\n{answer[:800]}\n\n"
                    f"【证据】\n{_evidence_text(evidence)}"
                ),
            },
        ]
        raw = (LLM_tools.chat_sync(messages, temperature=0, max_tokens=48) or "").strip()
        if not raw:
            return CritiqueResult(ok=True, source="error")
        ok, issue = _parse_verdict(raw)
        logger.info("critic verdict ok=%s issue=%r source=llm", ok, issue)
        return CritiqueResult(ok=ok, issue=issue, source="llm", raw=raw)
    except Exception as e:  # noqa: BLE001
        logger.debug("critic failed: %s", e)
        return CritiqueResult(ok=True, source="error")

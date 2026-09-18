"""
Input / Output Guardrail 链（借鉴 LangChain4j Guardrails）

决策：pass | fail | rewrite
成本排序：规则先于 LLM（本模块仅规则层，LLM judge 仍走 Corrective）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.tools.output_guard import VIDEO_QA_INSUFFICIENT_MSG

# 明显越权 / 注入探测（轻量，fail-closed 只拦高置信）
_INJECTION_PATTERNS = [
    re.compile(r"忽略(以上|之前|上面)?(的)?(所有)?指令", re.I),
    re.compile(r"ignore\s+(all\s+)?(previous|above)\s+instructions", re.I),
    re.compile(r"system\s*:\s*you\s+are", re.I),
]

# ViewHub 域外：纯闲聊政治/医疗诊断等（保守：只拦极端）
_OFF_DOMAIN = [
    re.compile(r"(如何制造|制作).{0,8}(炸弹|炸药|枪支)"),
    re.compile(r"(自杀|自残).{0,6}(方法|教程)"),
]


@dataclass
class GuardDecision:
    action: str  # pass | fail | rewrite
    reason: str = ""
    rewritten: str = ""
    meta: Optional[Dict[str, Any]] = None

    @property
    def ok(self) -> bool:
        return self.action == "pass"


def check_input(question: str) -> GuardDecision:
    q = (question or "").strip()
    if not q:
        return GuardDecision("fail", reason="empty_question")
    for pat in _INJECTION_PATTERNS:
        if pat.search(q):
            return GuardDecision("fail", reason="prompt_injection")
    for pat in _OFF_DOMAIN:
        if pat.search(q):
            return GuardDecision("fail", reason="off_domain_unsafe")
    return GuardDecision("pass")


def check_output_video_qa(
    answer: str,
    citations: Optional[List[Dict[str, Any]]] = None,
) -> GuardDecision:
    """片内问答：无依据则 rewrite 为拒答文案。"""
    text = (answer or "").strip()
    cites = citations or []
    if not text:
        return GuardDecision(
            "rewrite",
            reason="empty_answer",
            rewritten=VIDEO_QA_INSUFFICIENT_MSG,
        )
    if not cites:
        # 已是拒答文案则放行
        if VIDEO_QA_INSUFFICIENT_MSG[:20] in text:
            return GuardDecision("pass", reason="already_refuse")
        return GuardDecision(
            "rewrite",
            reason="missing_citations",
            rewritten=VIDEO_QA_INSUFFICIENT_MSG,
            meta={"original_len": len(text)},
        )
    # 有 citations 但回答过短且无引用标记 — 仍放行（引用块已结构化）
    return GuardDecision("pass")


def check_output_generic(answer: str) -> GuardDecision:
    text = (answer or "").strip()
    if not text:
        return GuardDecision("fail", reason="empty_answer")
    return GuardDecision("pass")

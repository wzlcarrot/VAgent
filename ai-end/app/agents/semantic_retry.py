"""
语义级重试（Semantic Retry）。

当一次检索证据不足时，不再用原问题重复检索，而是换一个"语义角度"改写后再检索。

与普通 query rewrite 的区别：
- rewrite 把口语问题规范化（同义），用于首次检索；
- semantic retry 在失败后生成**不同的检索视角**（并避开已失败的 query），提高二次命中率。
"""
from __future__ import annotations

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

_RETRY_SYSTEM = """你是检索重试改写器。上一轮检索没有找到足够证据。
请换一个与失败查询**不同**的角度，生成新的中文检索关键词（空格分隔，不超过 30 字）。

要求：
1. 不要重复已失败的查询
2. **用该主题下的具体领域术语/专业名词**，不要用「内容」「主题」「介绍」这类泛词
3. 优先列举视频字幕/讲解中**最可能出现**的 3-5 个具体概念
4. 只输出关键词，不要解释
"""


def _rule_reformulate(
    question: str,
    title: str,
    tags: str,
    previous_queries: List[str],
) -> str:
    """规则兜底：换用标题/标签/主题词等不同组合，避开已失败 query。"""
    candidates = [
        " ".join(p for p in [title.strip(), tags.strip(), "内容 主题 简介"] if p),
        " ".join(p for p in [tags.strip(), question.strip()] if p),
        " ".join(p for p in [title.strip(), question.strip()] if p),
        " ".join(p for p in [title.strip(), tags.strip()] if p),
    ]
    for candidate in candidates:
        candidate = candidate.strip()
        if len(candidate) >= 2 and candidate not in previous_queries:
            return candidate
    return ""


def reformulate_query(
    question: str,
    title: str = "",
    tags: str = "",
    previous_queries: Optional[List[str]] = None,
    *,
    attempt: int = 1,
) -> str:
    """生成与 previous_queries 不同的新检索 query；LLM 失败回退规则改写。"""
    prev = [q for q in (previous_queries or []) if q]
    question = (question or "").strip()

    try:
        from app.harness.llm_replay import replay_enabled, replay_semantic_retry

        if replay_enabled():
            replayed = replay_semantic_retry(question, prev)
            if replayed:
                return replayed
    except Exception:
        pass

    try:
        from app.tools.llm_tools import LLM_tools

        messages = [
            {"role": "system", "content": _RETRY_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"问题：{question}\n标题：{title or '无'}\n标签：{tags or '无'}\n"
                    f"已失败查询：{'；'.join(prev) if prev else '无'}"
                ),
            },
        ]
        out = (LLM_tools.chat_sync(messages, temperature=0.4, max_tokens=64) or "").strip()
        out = out.replace("\n", " ").strip().strip('"「」')
        if len(out) >= 2 and out not in prev:
            parts = [out] + ([tags.strip()] if tags.strip() else [])
            return " ".join(p for p in parts if p)
    except Exception as e:  # noqa: BLE001
        logger.debug("semantic retry LLM 失败，回退规则：%s", e)

    return _rule_reformulate(question, title, tags, prev)

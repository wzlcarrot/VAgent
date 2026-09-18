"""
片内视频问答检索：规则/LLM 改写 + 多轮召回 + 证据阈值 + Corrective + 引用。

Agentic RAG 轻量闭环：
1. query rewrite（规则优先，可选 LLM 增强）
2. 片内混合召回（最多多轮）
3. 生成后 corrective（证据支撑校验，失败则补搜或拒答）
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

MIN_EVIDENCE_SCORE = 0.25

_COLLOQUIAL_EXPANSIONS: Dict[str, str] = {
    "讲了啥": "讲了什么 内容 主题 简介",
    "说啥": "说了什么 内容 主题",
    "讲什么": "讲了什么 内容 主题",
    "讲啥的": "讲了什么 内容 主题",
    "干嘛的": "主题 内容 介绍",
    "干什么的": "主题 内容 介绍",
    "怎么样": "内容 主题 介绍",
    "好不好看": "内容 主题 评价",
    "重点": "重点 核心 主题 内容",
    "核心": "核心 重点 主题",
}

_METADATA_QUESTION_MARKERS = (
    "讲了什么", "讲了啥", "说啥", "讲什么", "介绍一下", "介绍这个", "总结",
    "主题", "内容是什么", "是什么视频", "这视频", "这个视频",
)


def format_evidence_for_prompt(knowledge: list, max_items: int = 3, max_len: int = 280) -> str:
    from app.tools.ranker import safe_prompt_escape

    lines = []
    for i, k in enumerate(knowledge[:max_items], start=1):
        if not isinstance(k, dict):
            continue
        raw = k.get("content") or k.get("block_content") or ""
        if not raw:
            continue
        block = k.get("block_type") or "chunk"
        score = k.get("score")
        score_s = f", score={float(score):.2f}" if score is not None else ""
        text = safe_prompt_escape(str(raw), max_len=max_len)
        lines.append(f"[{i}] ({block}{score_s}) {text}")
    return "\n".join(lines) if lines else "（无相关证据）"


def format_evidence_footer(knowledge: list, max_items: int = 3, max_len: int = 80) -> str:
    parts = []
    for i, k in enumerate(knowledge[:max_items], start=1):
        if not isinstance(k, dict):
            continue
        raw = (k.get("content") or k.get("block_content") or "").strip()
        if not raw:
            continue
        snippet = raw if len(raw) <= max_len else raw[: max_len - 1] + "…"
        parts.append(f"[{i}] {snippet}")
    if not parts:
        return ""
    return "\n\n依据：\n" + "\n".join(parts)


def build_citations(knowledge: list, max_items: int = 3, max_len: int = 120) -> List[Dict[str, Any]]:
    """结构化引用，供 SSE `citations` 事件消费（含可选 start_s 跳转）。"""
    out: List[Dict[str, Any]] = []
    for i, k in enumerate(knowledge[:max_items], start=1):
        if not isinstance(k, dict):
            continue
        raw = (k.get("content") or k.get("block_content") or "").strip()
        if not raw:
            continue
        snippet = raw if len(raw) <= max_len else raw[: max_len - 1] + "…"
        item: Dict[str, Any] = {
            "id": i,
            "snippet": snippet,
            "score": float(k.get("score") or 0),
            "block_type": k.get("block_type") or "chunk",
            "video_id": k.get("video_id") or "",
        }
        start_s = k.get("start_s")
        end_s = k.get("end_s")
        if start_s is not None:
            try:
                item["start_s"] = float(start_s)
            except (TypeError, ValueError):
                pass
        if end_s is not None:
            try:
                item["end_s"] = float(end_s)
            except (TypeError, ValueError):
                pass
        out.append(item)
    return out


def filter_scoped_chunks(
    chunks: List[Dict[str, Any]],
    video_id: str,
) -> List[Dict[str, Any]]:
    """片内硬过滤：丢掉 video_id 不一致的块，防止跨视频污染。"""
    if not video_id or not chunks:
        return chunks or []
    kept: List[Dict[str, Any]] = []
    dropped = 0
    for c in chunks:
        if not isinstance(c, dict):
            continue
        vid = (c.get("video_id") or "").strip()
        if vid and vid != video_id:
            dropped += 1
            continue
        # 无 video_id 字段的旧数据：补上当前 video_id 后保留
        item = dict(c)
        if not vid:
            item["video_id"] = video_id
        kept.append(item)
    if dropped:
        logger.warning(
            "filter_scoped_chunks: dropped %d cross-video chunks for video_id=%s",
            dropped, video_id,
        )
    return kept


def rewrite_video_qa_query_rules(question: str, title: str = "", tags: str = "") -> str:
    """规则改写：口语追加标准检索词。"""
    q = (question or "").strip()
    parts: List[str] = []
    if q:
        parts.append(q)
        for marker, expansion in _COLLOQUIAL_EXPANSIONS.items():
            if marker in q:
                parts.append(expansion)
                break
    if title:
        parts.append(title.strip())
    if tags:
        parts.append(tags.strip())
    return " ".join(p for p in parts if p)


def rewrite_video_qa_query(
    question: str,
    title: str = "",
    tags: str = "",
    *,
    use_llm: Optional[bool] = None,
) -> str:
    """
    Query 改写：默认规则；开启 LLM 时用短提示生成检索关键词，失败回退规则。
    """
    from app.config import settings

    rule_q = rewrite_video_qa_query_rules(question, title, tags)
    enabled = settings.effective_video_qa_llm_rewrite if use_llm is None else use_llm
    if not enabled or not (question or "").strip():
        return rule_q

    if use_llm is None or use_llm:
        try:
            from app.harness.llm_replay import replay_enabled, replay_query_rewrite
            if replay_enabled():
                replayed = replay_query_rewrite(question, title, tags)
                if replayed:
                    return replayed
        except Exception:
            pass

    try:
        from app.tools.llm_tools import LLM_tools

        messages = [
            {
                "role": "system",
                "content": (
                    "你是检索 query 改写器。把用户口语问题改写成适合在视频标题/简介/标签中检索的"
                    "简短中文关键词串（空格分隔，不超过 30 字）。只输出关键词，不要解释。"
                ),
            },
            {
                "role": "user",
                "content": f"问题：{question}\n标题：{title or '无'}\n标签：{tags or '无'}",
            },
        ]
        rewritten = LLM_tools.chat_sync(messages, temperature=0, max_tokens=64)
        rewritten = (rewritten or "").strip().replace("\n", " ")
        # 去掉可能的引号/序号
        rewritten = re.sub(r'^[\d\.、\-\s"「」]+', "", rewritten)
        if len(rewritten) < 2:
            return rule_q
        parts = [rewritten]
        if title:
            parts.append(title.strip())
        if tags:
            parts.append(tags.strip())
        return " ".join(parts)
    except Exception as e:
        logger.debug("LLM query rewrite failed, fallback rules: %s", e)
        return rule_q


# 兼容旧名
def rewrite_video_qa_query_legacy(*args, **kwargs):
    return rewrite_video_qa_query(*args, **kwargs)


def is_metadata_friendly_question(question: str) -> bool:
    q = (question or "").strip()
    if not q:
        return True
    return any(m in q for m in _METADATA_QUESTION_MARKERS)


def has_sufficient_evidence(results: List[Dict[str, Any]],
                            min_score: float = MIN_EVIDENCE_SCORE) -> bool:
    if not results:
        return False
    for r in results:
        if not isinstance(r, dict):
            continue
        if not (r.get("content") or r.get("block_content")):
            continue
        if float(r.get("score", 0)) >= min_score:
            return True
    return False


def verify_answer_grounded(
    answer: str,
    knowledge: list,
    question: str = "",
) -> Tuple[bool, str]:
    """
    Corrective：检查回答是否被证据支撑。

    返回 (ok, reason)。启发式 + 可选 LLM judge（settings.video_qa_llm_grounding）。
    """
    if not answer or not answer.strip():
        return False, "empty_answer"

    from app.tools.output_guard import FALLBACK_RESPONSE, VIDEO_QA_INSUFFICIENT_MSG

    if answer.strip() in (FALLBACK_RESPONSE, VIDEO_QA_INSUFFICIENT_MSG):
        return True, "explicit_refuse_or_fallback"

    if is_metadata_friendly_question(question) and not knowledge:
        return True, "metadata_friendly"

    texts = []
    for k in knowledge or []:
        if isinstance(k, dict):
            t = (k.get("content") or k.get("block_content") or "").strip()
            if t:
                texts.append(t)
    if not texts:
        return False, "no_evidence"

    if re.search(r"\[\d+\]", answer):
        return True, "has_citation_markers"

    def _bigrams(s: str) -> set:
        s = re.sub(r"\s+", "", s.lower())
        if len(s) < 2:
            return set()
        return {s[i: i + 2] for i in range(len(s) - 1)}

    ans_bg = _bigrams(answer)
    if not ans_bg:
        return False, "answer_too_short"

    best = 0.0
    best_text = ""
    for t in texts:
        ev_bg = _bigrams(t)
        if not ev_bg:
            continue
        overlap = len(ans_bg & ev_bg) / max(len(ans_bg), 1)
        if overlap > best:
            best = overlap
            best_text = t
    if best >= 0.08:
        return True, f"overlap={best:.2f}"

    # L2：短 LLM judge（演示/replay 模式走 replay_grounding_check）
    from app.config import settings
    if settings.effective_video_qa_llm_grounding:
        try:
            from app.harness.llm_replay import replay_enabled, replay_grounding_check
            if replay_enabled():
                replayed = replay_grounding_check(answer, best_text or texts[0])
                if replayed is not None:
                    return (replayed, "replay_grounding" if replayed else "replay_ungrounded")
            from app.tools.llm_tools import LLM_tools

            ev_snip = (best_text or texts[0])[:400]
            messages = [
                {
                    "role": "system",
                    "content": "你是事实核查器。只回答 yes 或 no：给定证据是否支撑回答中的关键事实？",
                },
                {
                    "role": "user",
                    "content": f"证据：{ev_snip}\n\n回答：{answer[:500]}",
                },
            ]
            verdict = (LLM_tools.chat_sync(messages, temperature=0, max_tokens=8) or "").strip().lower()
            if verdict.startswith("y") or verdict in ("是", "支持", "true"):
                return True, "llm_judge_yes"
            if verdict.startswith("n") or verdict in ("否", "不支持", "false"):
                return False, "llm_judge_no"
        except Exception as e:
            logger.debug("LLM grounding judge failed: %s", e)

    return False, f"low_overlap={best:.2f}"


def _merge_results(a: List[Dict[str, Any]], b: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
    seen = set()
    merged: List[Dict[str, Any]] = []
    for doc in a + b:
        if not isinstance(doc, dict):
            continue
        content = doc.get("content") or doc.get("block_content") or ""
        vid = doc.get("video_id") or ""
        key = f"{vid}:{content[:80]}"
        if key in seen or not content:
            continue
        seen.add(key)
        merged.append(doc)
    merged.sort(key=lambda d: float(d.get("score", 0)), reverse=True)
    return merged[:top_k]


def search_video_chunks(
    video_id: str,
    question: str,
    *,
    title: str = "",
    tags: str = "",
    top_k: int = 5,
    min_score: float = MIN_EVIDENCE_SCORE,
    rewrite_query: Optional[str] = None,
) -> tuple[List[Dict[str, Any]], bool]:
    """
    片内混合检索（最多多轮）。

    Returns:
        (chunks, knowledge_sufficient)
    """
    from app.tools.ranker import dual_recall_and_rerank

    if not video_id or not (question or title or tags):
        return [], False

    query1 = rewrite_query or rewrite_video_qa_query(question, title, tags)
    results = filter_scoped_chunks(
        dual_recall_and_rerank(query1, top_k=top_k, video_id=video_id),
        video_id,
    )
    sufficient = has_sufficient_evidence(results, min_score)

    if not sufficient:
        query2 = " ".join(p for p in [title.strip(), tags.strip(), question.strip()] if p)
        if query2 and query2 != query1:
            results2 = filter_scoped_chunks(
                dual_recall_and_rerank(query2, top_k=top_k, video_id=video_id),
                video_id,
            )
            results = _merge_results(results, results2, top_k)
            sufficient = has_sufficient_evidence(results, min_score)
        if not sufficient and title:
            query3 = title.strip()
            if query3 and query3 not in (query1, query2):
                results3 = filter_scoped_chunks(
                    dual_recall_and_rerank(query3, top_k=top_k, video_id=video_id),
                    video_id,
                )
                results = _merge_results(results, results3, top_k)
                sufficient = has_sufficient_evidence(results, min_score)

    if is_metadata_friendly_question(question):
        sufficient = sufficient or bool(results)

    logger.debug(
        "search_video_chunks video_id=%s sufficient=%s hits=%d",
        video_id, sufficient, len(results),
    )
    return results, sufficient


def corrective_retrieve_once(
    video_id: str,
    question: str,
    *,
    title: str = "",
    tags: str = "",
    existing: Optional[List[Dict[str, Any]]] = None,
    top_k: int = 5,
) -> tuple[List[Dict[str, Any]], bool]:
    """Corrective 补搜：用标题主导再捞一轮，与已有证据合并。"""
    from app.tools.ranker import dual_recall_and_rerank

    query = " ".join(p for p in [title.strip(), tags.strip(), "内容 主题 简介", question.strip()] if p)
    extra = dual_recall_and_rerank(query, top_k=top_k, video_id=video_id) if video_id and query else []
    extra = filter_scoped_chunks(extra, video_id)
    merged = _merge_results(existing or [], extra, top_k)
    return merged, has_sufficient_evidence(merged) or is_metadata_friendly_question(question)

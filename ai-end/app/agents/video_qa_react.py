"""
片内视频问答 —— Bounded ReAct 检索（max_steps 可配置）。

Agent 在证据不足时可多次调用 search_video_chunks，再交给下游 LLM 生成与 Corrective。
演示模式下走 llm_replay，仍执行真实检索工具（与生产路径一致，仅 mock LLM）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from app.agents.react_guard import DuplicateCallGuard
from app.agents.workflows.constants import WorkflowType
from app.agents.workflows.harness_helpers import invoke_with_governor
from app.config import settings
from app.harness.agent_loop import (
    STOP_SUFFICIENT,
    AgentStep,
    Observation,
    ToolCall,
    normalize_tool_calls,
    run_agent_loop,
)
from app.tools.llm_tools import LLM_tools
from app.tools.video_qa_retrieval import (
    has_sufficient_evidence,
    search_video_chunks,
)

logger = logging.getLogger(__name__)

VIDEO_QA_REACT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_video_chunks",
            "description": (
                "在当前视频内检索与问题相关的证据片段。"
                "证据不足时可换关键词再次调用；证据足够后停止调用并直接回答用户。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "用于检索的问题或关键词（可改写口语）",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回片段数",
                        "default": 5,
                    },
                },
                "required": ["question"],
            },
        },
    }
]

_REACT_SYSTEM = """你是 ViewHub 片内视频问答 Agent。

你可以调用工具 search_video_chunks 在当前视频内检索证据。
规则：
1. 先检索再回答；口语问题可改写检索词
2. 最多调用 {max_steps} 次工具；证据足够后必须直接给出简洁中文回答
3. 回答中引用证据时使用 [1][2] 标注
4. 证据不足时说明无法从视频资料中确认，不要编造
"""


def _merge_knowledge(existing: List[Dict[str, Any]], new_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    merged: List[Dict[str, Any]] = []
    for doc in existing + new_items:
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
    return merged


def _execute_search_tool(
    session_id: str,
    video_id: str,
    question: str,
    title: str,
    tags: str,
    top_k: int,
) -> Tuple[List[Dict[str, Any]], bool]:
    raw = invoke_with_governor(
        session_id,
        WorkflowType.VIDEO_QA,
        "search_video_chunks",
        lambda: search_video_chunks(
            video_id,
            question,
            title=title,
            tags=tags,
            top_k=top_k,
        ),
    )
    if isinstance(raw, tuple) and len(raw) == 2:
        return raw[0], raw[1]
    return [], False


def _semantic_retry_retrieval(
    session_id: str,
    video_id: str,
    question: str,
    title: str,
    tags: str,
    tried_queries: List[str],
    knowledge: List[Dict[str, Any]],
    sufficient: bool,
) -> Tuple[List[Dict[str, Any]], bool]:
    """证据不足时的语义重试：换角度改写 query 再检索，最多 N 轮。

    与首轮改写不同，这里显式避开已失败的 query，避免"重复同一检索"。
    """
    from app.agents.semantic_retry import reformulate_query

    attempts = max(0, int(settings.video_qa_semantic_retry_max))
    for attempt in range(1, attempts + 1):
        if sufficient:
            break
        new_query = reformulate_query(question, title, tags, tried_queries, attempt=attempt)
        if not new_query or new_query in tried_queries:
            break
        tried_queries.append(new_query)
        chunks, hit = _execute_search_tool(session_id, video_id, new_query, title, tags, 5)
        knowledge = _merge_knowledge(knowledge, chunks)
        sufficient = sufficient or hit or has_sufficient_evidence(knowledge)
        logger.info(
            "video_qa semantic retry attempt=%d query=%r sufficient=%s",
            attempt, new_query, sufficient,
        )
    return knowledge, sufficient


def _format_tool_result(chunks: List[Dict[str, Any]]) -> str:
    if not chunks:
        return "（未检索到相关证据）"
    lines = []
    for i, c in enumerate(chunks[:5], start=1):
        text = (c.get("content") or c.get("block_content") or "")[:200]
        score = c.get("score")
        score_s = f", score={float(score):.2f}" if score is not None else ""
        lines.append(f"[{i}] ({c.get('block_type', 'chunk')}{score_s}) {text}")
    return "\n".join(lines)


def run_video_qa_react_retrieval(
    *,
    video_id: str,
    question: str,
    title: str = "",
    tags: str = "",
    session_id: str = "",
    max_steps: int | None = None,
) -> Tuple[List[Dict[str, Any]], bool, int, str, str]:
    """
    Bounded ReAct 检索（由通用执行引擎 app/harness/agent_loop.py 驱动）。

    Returns:
        (knowledge, sufficient, steps_used, agent_note, stop_reason)
        agent_note: ReAct 最终文本（若模型提前作答则为草稿，下游 llm_node 仍会正式生成）
        stop_reason: answered|max_steps|duplicate_repeat|timeout|error|sufficient|skipped|disabled
    """
    if not video_id or not (question or title):
        return [], False, 0, "", "skipped"

    if not settings.video_qa_react_enabled:
        chunks, sufficient = search_video_chunks(video_id, question, title=title, tags=tags, top_k=5)
        return chunks, sufficient, 0, "", "disabled"

    limit = max_steps if max_steps is not None else settings.video_qa_react_max_steps
    limit = max(1, min(limit, 5))

    messages: List[Dict[str, Any]] = [
        {
            "role": "system",
            "content": _REACT_SYSTEM.format(max_steps=limit),
        },
        {
            "role": "user",
            "content": (
                f"video_id: {video_id}\n"
                f"标题: {title or '无'}\n"
                f"标签: {tags or '无'}\n"
                f"用户问题: {question}"
            ),
        },
    ]

    knowledge: List[Dict[str, Any]] = []
    sufficient = False
    tried_queries: List[str] = []

    def _decide(_step: int, msgs: List[Dict[str, Any]]) -> AgentStep | None:
        result = LLM_tools.chat_with_tools(
            msgs,
            VIDEO_QA_REACT_TOOLS,
            temperature=0.2,
            max_tokens=600,
        )
        if not result:
            logger.warning("video_qa ReAct: chat_with_tools 返回空，回退单次检索")
            return None
        return AgentStep(calls=normalize_tool_calls(result), content=(result.get("content") or ""))

    def _execute(call: ToolCall) -> Observation:
        query = str(call.args.get("question") or question).strip()
        top_k = int(call.args.get("top_k") or 5)
        chunks, hit = _execute_search_tool(session_id, video_id, query, title, tags, top_k)
        return Observation(
            text=_format_tool_result(chunks),
            data={"query": query, "chunks": chunks, "hit": hit},
        )

    def _observe(_call: ToolCall, obs: Observation) -> None:
        nonlocal knowledge, sufficient
        data = obs.data or {}
        tried_queries.append(data.get("query", ""))
        knowledge = _merge_knowledge(knowledge, data.get("chunks") or [])
        sufficient = sufficient or bool(data.get("hit")) or has_sufficient_evidence(knowledge)

    def _should_stop() -> str | None:
        # 可选扩展点：证据已足够时提前收口，省一次 LLM 调用（默认关闭）
        if settings.video_qa_react_stop_on_sufficient and sufficient:
            return STOP_SUFFICIENT
        return None

    outcome = run_agent_loop(
        messages=messages,
        decide=_decide,
        execute=_execute,
        observe=_observe,
        max_steps=limit,
        should_stop=_should_stop,
        guard=DuplicateCallGuard(),
        nudge_after=settings.agent_loop_nudge_after,
        force_stop_after=settings.agent_loop_force_stop_after,
        deadline_seconds=settings.agent_loop_deadline_seconds,
        log_tag="video_qa_react",
    )
    agent_note = outcome.answer
    steps_used = outcome.steps

    if not knowledge:
        tried_queries.append(question)
        chunks, hit = search_video_chunks(video_id, question, title=title, tags=tags, top_k=5)
        knowledge = chunks
        sufficient = hit

    if not sufficient:
        sufficient = has_sufficient_evidence(knowledge)

    if not sufficient and settings.video_qa_semantic_retry_enabled:
        knowledge, sufficient = _semantic_retry_retrieval(
            session_id, video_id, question, title, tags, tried_queries, knowledge, sufficient,
        )

    logger.info(
        "video_qa ReAct done stop_reason=%s steps=%d hits=%d sufficient=%s",
        outcome.stop_reason, steps_used, len(knowledge), sufficient,
    )
    return knowledge, sufficient, steps_used, agent_note, outcome.stop_reason

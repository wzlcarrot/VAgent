"""
平台客服 Bounded ReAct（orchestration_mode=agent 时替代 chat LangGraph）。

最多 N 次 retrieve_knowledge / retrieve_platform_docs，再生成回答。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from app.agents.react_guard import DuplicateCallGuard
from app.agents.workflows.constants import WorkflowType
from app.agents.workflows.harness_helpers import invoke_with_governor
from app.config import settings
from app.harness.agent_loop import (
    AgentStep,
    Observation,
    ToolCall,
    normalize_tool_calls,
    parse_tool_call,
    run_agent_loop,
)
from app.tools.llm_tools import LLM_tools
from app.tools.rag_tools import RAGTools

logger = logging.getLogger(__name__)

CHAT_REACT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "retrieve_knowledge",
            "description": (
                "检索 ViewHub 平台知识库，覆盖平台功能说明（FAQ）与视频元数据。"
                "用户询问平台怎么用、有什么功能、某类视频是否存在时调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "检索问题或关键词"},
                    "top_k": {"type": "integer", "default": 5},
                },
                "required": ["question"],
            },
        },
    },
]

_SYSTEM = """你是 ViewHub 官方智能助手 Agent。
可调用 retrieve_knowledge 检索平台功能说明与视频元数据后再回答。
规则：最多 {max_steps} 次工具调用；证据足够后直接简洁中文回答；不知道就说不知道。"""


def _retrieve_all_sources(query: str, top_k: int) -> List[Dict[str, Any]]:
    """统一检索：视频元数据（video_info）+ 平台文档（FAQ），合并去重后按分排序。

    合并原因：原先暴露 retrieve_knowledge / retrieve_platform_docs 两个工具，
    职责描述重叠，LLM 难以区分（评测中同一问题两次选择不一致）。合并为单一入口。
    """
    merged: List[Dict[str, Any]] = []
    try:
        merged.extend(RAGTools.retrieve_knowledge(query, top_k=top_k) or [])
    except Exception as e:  # noqa: BLE001
        logger.debug("retrieve_knowledge failed: %s", e)
    try:
        merged.extend(RAGTools.retrieve_platform_docs(query, top_k=3) or [])
    except Exception as e:  # noqa: BLE001
        logger.debug("retrieve_platform_docs failed: %s", e)

    seen = set()
    out: List[Dict[str, Any]] = []
    for doc in merged:
        if not isinstance(doc, dict):
            continue
        key = (doc.get("content") or doc.get("title") or "")[:80]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(doc)
    out.sort(key=lambda d: float(d.get("score") or 0), reverse=True)
    return out[: max(top_k, 5)]


def _exec_tool(name: str, args: Dict[str, Any], session_id: str) -> List[Dict[str, Any]]:
    q = (args.get("question") or "").strip()
    top_k = int(args.get("top_k") or 5)
    if name == "retrieve_knowledge":
        return invoke_with_governor(
            session_id, WorkflowType.CHAT, "retrieve_knowledge",
            lambda: _retrieve_all_sources(q, top_k),
        ) or []
    return []


def _parse_tool_call(tc: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    """兼容规范化（``tool_name``）与 OpenAI 原生（``function.name``）两种结构。"""
    return parse_tool_call(tc)


def run_chat_react(
    question: str,
    conversation_history: List[Dict[str, str]] | None = None,
    session_id: str = "",
) -> Dict[str, Any]:
    max_steps = max(1, settings.chat_react_max_steps)
    history = conversation_history or []
    system_prompt = _SYSTEM.format(max_steps=max_steps)
    system_notes = [t["system_memory"] for t in history if isinstance(t, dict) and t.get("system_memory")]
    if system_notes:
        system_prompt += "\n\n" + "\n\n".join(system_notes)
    knowledge: List[Dict[str, Any]] = []
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]
    for turn in history[-settings.context_max_rounds:]:
        if not isinstance(turn, dict):
            continue
        if turn.get("user"):
            messages.append({"role": "user", "content": turn["user"]})
        if turn.get("assistant"):
            messages.append({"role": "assistant", "content": turn["assistant"]})
    messages.append({"role": "user", "content": question})

    def _decide(step: int, msgs: List[Dict[str, Any]]) -> AgentStep | None:
        if settings.effective_llm_replay_enabled:
            from app.harness.llm_replay import replay_chat_react_step

            raw = replay_chat_react_step(question, step, len(knowledge))
            if raw:
                if raw.get("final_answer"):
                    return AgentStep(calls=[], content=raw["final_answer"])
                if raw.get("tool_name"):
                    return AgentStep(calls=[ToolCall(
                        name=raw["tool_name"], args=raw.get("args") or {}, call_id=f"replay-{step}",
                    )])
                return None
        resp = LLM_tools.chat_with_tools(msgs, CHAT_REACT_TOOLS, temperature=0.2, max_tokens=800)
        if not resp:
            return None
        return AgentStep(calls=normalize_tool_calls(resp), content=(resp.get("content") or ""))

    def _execute(call: ToolCall) -> Observation:
        try:
            docs = _exec_tool(call.name, call.args, session_id) or []
        except Exception as e:  # noqa: BLE001
            logger.warning("chat React 工具执行失败: %s", e)
            return Observation(text=f"工具执行失败：{e}", is_error=True)
        text = json.dumps(docs[:8], ensure_ascii=False)[:3000] if docs else ""
        return Observation(text=text, data=docs)

    def _observe(_call: ToolCall, obs: Observation) -> None:
        knowledge.extend(obs.data or [])

    def _finalize() -> str:
        ctx = "\n".join(
            (d.get("content") or d.get("block_content") or "")[:200]
            for d in knowledge[:6]
        )
        return LLM_tools.chat_sync([
            {"role": "system", "content": "根据检索内容简洁回答 ViewHub 平台问题。"},
            {"role": "user", "content": f"问题：{question}\n\n检索：\n{ctx}"},
        ]) or "抱歉，我暂时无法回答这个问题。"

    outcome = run_agent_loop(
        messages=messages,
        decide=_decide,
        execute=_execute,
        observe=_observe,
        max_steps=max_steps,
        finalize=_finalize,
        guard=DuplicateCallGuard(),
        nudge_after=settings.agent_loop_nudge_after,
        force_stop_after=settings.agent_loop_force_stop_after,
        deadline_seconds=settings.agent_loop_deadline_seconds,
        log_tag="chat_react",
    )

    answer = outcome.answer or "抱歉，我暂时无法回答这个问题。"
    llm_messages = [
        {"role": "system", "content": "你是 ViewHub 官方智能助手。"},
        {"role": "user", "content": question},
    ]
    return {
        "answer": answer,
        "full_response": answer,
        "workflow_type": WorkflowType.CHAT,
        "llm_messages": llm_messages,
        "knowledge": knowledge,
        "agent_mode": "react",
        "react_steps": outcome.steps,
        "react_tools": outcome.tools,
        "react_stop_reason": outcome.stop_reason,
        "react_nudges": outcome.nudges,
    }

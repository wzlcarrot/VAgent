"""
LLM Replay —— 从 fixture 回放固定响应，CI / 演示零 token、零 flaky。

环境变量 VAGENT_LLM_REPLAY=1 或 settings.demo_mode / VAGENT_DEMO_MODE=1 启用。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from app.agents.workflows.constants import WorkflowType

# 路由器 replay：按用户问题关键词推断 intent（演示不依赖 Function Calling API）
_ROUTER_RULES: List[tuple[List[str], str]] = [
    (["讲了什么", "视频"], WorkflowType.VIDEO_QA),
    (["讲了啥", "视频"], WorkflowType.VIDEO_QA),
    (["视频", "讲"], WorkflowType.VIDEO_QA),
    (["推荐", "视频"], WorkflowType.RECOMMEND),
    (["推荐", "科技"], WorkflowType.RECOMMEND),
    (["好看的", "视频"], WorkflowType.RECOMMEND),
    (["有什么", "好看"], WorkflowType.RECOMMEND),
    (["硬币"], WorkflowType.USER_DATA),
    (["关注", "up"], WorkflowType.USER_DATA),
    (["点赞"], WorkflowType.USER_DATA),
    (["收藏"], WorkflowType.USER_DATA),
    (["播放", "历史"], WorkflowType.USER_DATA),
    (["看过"], WorkflowType.USER_DATA),
]


def replay_enabled() -> bool:
    from app.config import settings
    if settings.effective_llm_replay_enabled:
        return True
    return os.environ.get("VAGENT_LLM_REPLAY", "").lower() in ("1", "true", "yes")


def fixtures_root() -> Path:
    from app.config import settings
    root = Path(settings.llm_replay_fixtures_dir)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[2] / root
    return root


def load_fixture(name: str) -> Dict[str, Any]:
    path = fixtures_root() / name / "session.json"
    if not path.exists():
        raise FileNotFoundError(f"replay fixture missing: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _user_text(messages: List[Dict[str, Any]]) -> str:
    return " ".join(
        str(m.get("content", "")) for m in messages if m.get("role") == "user"
    ).lower()


def match_response(messages: List[Dict[str, Any]], fixture: Dict[str, Any]) -> Optional[str]:
    """按 user 内容关键词匹配 fixture 中的 canned 响应。"""
    user_text = _user_text(messages)
    for entry in fixture.get("responses", []):
        keywords = entry.get("match_keywords") or []
        if not keywords or all(kw.lower() in user_text for kw in keywords):
            return entry.get("content", "")
    return fixture.get("default_response")


def replay_chat(messages: List[Dict[str, Any]], scenario: str = "default") -> Optional[str]:
    if not replay_enabled():
        return None
    try:
        fixture = load_fixture(scenario)
        return match_response(messages, fixture)
    except FileNotFoundError:
        return None


def _tool_call_result(intent_type: str) -> Dict[str, Any]:
    return {
        "tool_call": True,
        "tool_calls": [{
            "tool_call_id": "replay-classify",
            "tool_name": "classify_intent",
            "arguments": {"intent_type": intent_type},
        }],
        "tool_call_id": "replay-classify",
        "tool_name": "classify_intent",
        "arguments": {"intent_type": intent_type},
        "content": "",
        "usage": {},
    }


def _is_video_qa_react_tools(tools: Optional[List[Dict[str, Any]]]) -> bool:
    if not tools:
        return False
    for tool in tools:
        fn = tool.get("function") or {}
        if fn.get("name") == "search_video_chunks":
            return True
    return False


def replay_query_rewrite(question: str, title: str = "", tags: str = "") -> Optional[str]:
    """
    演示模式 query 改写：走与生产相同的改写分支，但不调真实 LLM API。
    """
    if not replay_enabled():
        return None
    from app.tools.video_qa_retrieval import rewrite_video_qa_query_rules

    rule_q = rewrite_video_qa_query_rules(question, title, tags)
    q = (question or "").strip()
    if any(m in q for m in ("讲了啥", "讲了什么", "说啥", "讲什么")):
        parts = [rule_q, title.strip() if title else "", tags.strip() if tags else ""]
        return " ".join(p for p in parts if p)
    return rule_q


def replay_chat_react_step(question: str, step: int, knowledge_len: int) -> Optional[Dict[str, Any]]:
    """Chat ReAct replay：先 retrieve_knowledge，再 canned 回答。"""
    if not replay_enabled():
        return None
    if step == 0 and knowledge_len == 0:
        return {
            "tool_name": "retrieve_knowledge",
            "args": {"question": question, "top_k": 5},
        }
    text = replay_chat([{"role": "user", "content": question}], "default")
    return {"final_answer": text or "ViewHub 支持投稿、弹幕、投币与 AI 智能助手。"}


def _is_chat_react_tools(tools: Optional[List[Dict[str, Any]]]) -> bool:
    if not tools:
        return False
    for tool in tools:
        fn = tool.get("function") or {}
        if fn.get("name") in ("retrieve_knowledge", "retrieve_platform_docs"):
            return True
    return False


def replay_video_qa_react_step(
    messages: List[Dict[str, Any]],
    scenario: str = "default",
) -> Dict[str, Any]:
    """Video QA ReAct：第一步调检索工具，见到 tool 结果后返回最终草稿。"""
    if any(m.get("role") == "tool" for m in messages):
        text = replay_chat(messages, scenario) or "这是演示模式的视频问答草稿[1]。"
        return {"tool_call": False, "content": text, "usage": {}}

    user_text = _user_text(messages)
    question = user_text
    if "用户问题:" in user_text:
        question = user_text.split("用户问题:")[-1].strip()
    return {
        "tool_call": True,
        "tool_calls": [{
            "tool_call_id": "replay-vqa-search",
            "tool_name": "search_video_chunks",
            "arguments": {"question": question or user_text, "top_k": 5},
        }],
        "tool_call_id": "replay-vqa-search",
        "tool_name": "search_video_chunks",
        "arguments": {"question": question or user_text, "top_k": 5},
        "content": "",
        "usage": {},
    }


def replay_chat_with_tools(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    scenario: str = "default",
) -> Optional[Dict[str, Any]]:
    """演示/CI 下模拟 Function Calling 路由或 Video QA ReAct。"""
    if not replay_enabled():
        return None

    if _is_video_qa_react_tools(tools):
        return replay_video_qa_react_step(messages, scenario)

    if _is_chat_react_tools(tools):
        user_text = _user_text(messages)
        q = user_text.split("用户问题:")[-1].strip() if "用户问题:" in user_text else user_text
        has_tool = any(m.get("role") == "tool" for m in messages)
        if has_tool:
            text = replay_chat(messages, scenario) or "ViewHub 支持投稿、弹幕与 AI 助手。"
            return {"tool_call": False, "content": text, "usage": {}}
        return {
            "tool_call": True,
            "tool_calls": [{
                "tool_call_id": "replay-chat-search",
                "tool_name": "retrieve_knowledge",
                "arguments": {"question": q or user_text, "top_k": 5},
            }],
            "content": "",
            "usage": {},
        }

    user_text = _user_text(messages)
    # fixture 可显式指定 router 规则
    try:
        fixture = load_fixture(scenario)
        for entry in fixture.get("router_rules", []):
            keywords = entry.get("match_keywords") or []
            intent = entry.get("intent_type")
            if intent and keywords and all(kw.lower() in user_text for kw in keywords):
                return _tool_call_result(intent)
    except FileNotFoundError:
        pass
    for keywords, intent in _ROUTER_RULES:
        if all(kw.lower() in user_text for kw in keywords):
            return _tool_call_result(intent)
    return _tool_call_result(WorkflowType.CHAT)


async def replay_stream_chat(
    messages: List[Dict[str, Any]],
    scenario: str = "default",
    chunk_size: int = 12,
) -> AsyncIterator[str]:
    """流式回放：按小块 yield，保留打字机效果。"""
    text = replay_chat(messages, scenario) or "这是演示模式的流式回复。"
    for i in range(0, len(text), chunk_size):
        yield text[i: i + chunk_size]


def replay_grounding_check(answer: str, evidence_text: str) -> Optional[bool]:
    """
    演示模式下 LLM grounding：证据与回答有字面重叠或含 [n] 则 grounded。
    返回 None 表示未启用 replay，应走真实 LLM。
    """
    if not replay_enabled():
        return None
    if not answer or not evidence_text:
        return False
    if "[" in answer and "]" in answer:
        return True
    ev = evidence_text[:80].lower()
    ans = answer.lower()
    return any(len(w) >= 2 and w in ans for w in ev.split()[:6])


def replay_critique(question: str, answer: str, evidence_text: str) -> Optional[str]:
    """
    演示模式独立评审：含引用标记或在证据中有字面重叠则通过。
    返回 None 表示未启用 replay，应走真实 LLM。
    """
    if not replay_enabled():
        return None
    if not answer:
        return "PROBLEM: 空回答"
    if "[" in answer and "]" in answer:
        return "OK"
    ev = (evidence_text or "")[:80].lower()
    ans = answer.lower()
    if any(len(w) >= 2 and w in ans for w in ev.split()[:6]):
        return "OK"
    return "PROBLEM: 关键事实缺少证据支撑"


def replay_semantic_retry(question: str, previous_queries: List[str]) -> Optional[str]:
    """演示模式语义重试：换用"主题 内容"角度，避开已失败 query。"""
    if not replay_enabled():
        return None
    prev = previous_queries or []
    for candidate in (f"{question} 主题 内容", f"{question} 简介 概述", f"{question} 核心 重点"):
        if candidate not in prev:
            return candidate
    return None


def replay_memory_judge(new_content: str, existing: List[Dict[str, Any]]) -> Optional[str]:
    """演示模式记忆判定：新内容与某条已有记忆高度重合 → SUPERSEDE，否则 ADD。"""
    if not replay_enabled():
        return None
    new = (new_content or "").strip()
    for mem in existing or []:
        old = (mem.get("content") or "").strip()
        if not old:
            continue
        if new == old:
            return f'{{"action":"SUPERSEDE","target_id":{mem.get("id")}}}'
        if len(new) >= 4 and (new in old or old in new):
            return f'{{"action":"SUPERSEDE","target_id":{mem.get("id")}}}'
    return '{"action":"ADD","target_id":null}'


def replay_memory_consolidate(items: List[Dict[str, Any]]) -> Optional[str]:
    """演示模式记忆合并：仅按 content 去重（保守，不臆造合并）。"""
    if not replay_enabled():
        return None
    seen = set()
    merged = []
    for it in items or []:
        content = str(it.get("content") or "").strip()
        key = content.lower()
        if content and key not in seen:
            seen.add(key)
            merged.append({"type": it.get("type") or "preference", "content": content})
    return json.dumps({"items": merged}, ensure_ascii=False)


def _infer_intent_by_rules(question: str) -> str:
    """按关键词规则推断意图（演示 replay 用，与生产路由的规则层同源思路）。"""
    q = (question or "").lower()
    for keywords, intent in _ROUTER_RULES:
        if all(kw.lower() in q for kw in keywords):
            return intent
    return WorkflowType.CHAT


def replay_intent_cot(question: str, intents: List[str]) -> Optional[str]:
    """演示模式 CoT：按关键词规则生成"推理过程 + 结论"文本。

    返回 None 表示未启用 replay，应走真实 LLM。
    """
    if not replay_enabled():
        return None
    intent = _infer_intent_by_rules(question)
    if intents and intent not in intents:
        intent = intents[0]
    return (
        f"用户的问题围绕「{intent}」相关场景展开。\n"
        f"结合关键词判断，最匹配的意图是 {intent}。\n"
        f"结论：{intent}"
    )

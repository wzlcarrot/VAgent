"""chat_react 与 orchestration_mode 单测。"""
import json
from unittest.mock import patch

from app.agents.chat_react import _parse_tool_call, run_chat_react


def test_parse_tool_call_normalized_and_openai():
    """规范化格式（tool_name）与 OpenAI 原生格式（function.name）都要能解析。"""
    n1, a1 = _parse_tool_call(
        {"tool_call_id": "c1", "tool_name": "retrieve_knowledge", "arguments": {"question": "x"}}
    )
    assert n1 == "retrieve_knowledge" and a1 == {"question": "x"}

    n2, a2 = _parse_tool_call(
        {"id": "c2", "function": {"name": "retrieve_platform_docs", "arguments": '{"top_k": 3}'}}
    )
    assert n2 == "retrieve_platform_docs" and a2 == {"top_k": 3}

    n3, a3 = _parse_tool_call({})
    assert n3 == "" and a3 == {}


def test_chat_react_demo_replay():
    with patch("app.config.settings.demo_mode", True), \
         patch("app.config.settings.llm_replay_enabled", False), \
         patch("app.agents.chat_react._exec_tool", return_value=[{"content": "投稿与弹幕"}]), \
         patch("app.harness.llm_replay.replay_chat_react_step", side_effect=[
             {"tool_name": "retrieve_knowledge", "args": {"question": "平台功能", "top_k": 5}},
             {"final_answer": "ViewHub 支持投稿与弹幕。"},
         ]):
        r = run_chat_react("平台有什么功能", session_id="s1")
    assert "投稿" in r["answer"]
    assert r.get("agent_mode") == "react"


def test_chat_react_breaks_on_duplicate_tool_call():
    """模型反复用相同参数调同一工具时，第 2 步应被拦截并提前终止。"""
    def _looping_tools(messages, tools, **kwargs):
        return {
            "tool_calls": [{
                "id": "c1",
                "function": {
                    "name": "retrieve_knowledge",
                    "arguments": json.dumps({"question": "平台功能", "top_k": 5}),
                },
            }],
            "content": "",
        }

    calls = []

    def _fake_exec(name, args, session_id):
        calls.append(name)
        return [{"content": "投稿与弹幕"}]

    with patch("app.config.settings.demo_mode", False), \
         patch("app.config.settings.llm_replay_enabled", False), \
         patch("app.config.settings.chat_react_max_steps", 5), \
         patch("app.agents.chat_react.LLM_tools.chat_with_tools", side_effect=_looping_tools), \
         patch("app.agents.chat_react._exec_tool", side_effect=_fake_exec), \
         patch("app.agents.chat_react.LLM_tools.chat_sync", return_value="根据检索内容回答"):
        r = run_chat_react("平台有什么功能", session_id="s1")
    assert len(calls) == 1  # 未跑满 5 步，重复调用被拦截
    assert r["answer"]


def test_chat_react_executes_normalized_tool_call():
    """回归：chat_with_tools 返回规范化格式（tool_name）时，工具必须真正执行。

    历史 bug：chat ReAct 只读 tc["function"]["name"]，工具名恒为空串 → 从未检索。
    """
    executed = []

    def _fake_tools(messages, tools, **kwargs):
        if any(m.get("role") == "tool" for m in messages):
            return {"content": "平台支持投稿与弹幕。", "tool_calls": []}
        return {
            "tool_call": True,
            "tool_calls": [{
                "tool_call_id": "call_1",
                "tool_name": "retrieve_knowledge",
                "arguments": {"question": "平台功能", "top_k": 3},
            }],
            "content": "",
        }

    def _fake_exec(name, args, session_id):
        executed.append((name, args))
        return [{"content": "平台支持投稿与弹幕"}]

    with patch("app.config.settings.demo_mode", False), \
         patch("app.config.settings.llm_replay_enabled", False), \
         patch("app.config.settings.chat_react_max_steps", 3), \
         patch("app.agents.chat_react.LLM_tools.chat_with_tools", side_effect=_fake_tools), \
         patch("app.agents.chat_react._exec_tool", side_effect=_fake_exec):
        r = run_chat_react("平台有什么功能", session_id="s1")
    assert executed and executed[0][0] == "retrieve_knowledge"
    assert r["react_tools"] == ["retrieve_knowledge"]
    assert r["react_steps"] == 2
    assert "投稿" in r["answer"]


def test_chat_react_merges_both_knowledge_sources():
    """合并工具：retrieve_knowledge 应同时覆盖视频元数据与平台 FAQ，并去重。"""
    import app.agents.chat_react as cr

    with patch.object(cr.RAGTools, "retrieve_knowledge", return_value=[
        {"content": "视频A 的简介", "score": 0.9},
        {"content": "重复内容", "score": 0.5},
    ]), patch.object(cr.RAGTools, "retrieve_platform_docs", return_value=[
        {"content": "如何上传视频", "score": 0.8},
        {"content": "重复内容", "score": 0.4},
    ]):
        out = cr._retrieve_all_sources("上传视频", 5)
    contents = [d["content"] for d in out]
    assert "如何上传视频" in contents and "视频A 的简介" in contents
    assert contents.count("重复内容") == 1  # 去重
    assert contents[0] == "视频A 的简介"  # 按 score 降序

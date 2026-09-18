"""语义级重试（Semantic Retry）测试。"""
from unittest.mock import patch

from app.agents.semantic_retry import reformulate_query


def test_reformulate_via_llm():
    with patch("app.harness.llm_replay.replay_enabled", return_value=False), \
         patch("app.tools.llm_tools.LLM_tools.chat_sync", return_value="编程教学 入门"):
        out = reformulate_query(
            "讲了啥", title="Python教程", tags="编程",
            previous_queries=["讲了啥 Python教程"],
        )
    assert out.startswith("编程教学")


def test_reformulate_avoids_previous_queries():
    """LLM 返回与已失败 query 相同 → 回退规则改写。"""
    with patch("app.harness.llm_replay.replay_enabled", return_value=False), \
         patch("app.tools.llm_tools.LLM_tools.chat_sync", return_value="重复查询"):
        out = reformulate_query(
            "讲了啥", title="Python教程", tags="编程",
            previous_queries=["重复查询"],
        )
    assert out != "重复查询"
    assert "Python教程" in out or "编程" in out


def test_reformulate_rule_fallback_on_llm_failure():
    with patch("app.harness.llm_replay.replay_enabled", return_value=False), \
         patch("app.tools.llm_tools.LLM_tools.chat_sync", side_effect=RuntimeError("boom")):
        out = reformulate_query("讲了啥", title="Python教程", tags="编程", previous_queries=[])
    assert "Python教程" in out and "编程" in out


def test_reformulate_replay_differs_from_previous():
    with patch("app.config.settings.demo_mode", True), \
         patch("app.harness.llm_replay.replay_enabled", return_value=True):
        prev = ["讲了啥 主题 内容"]
        out = reformulate_query("讲了啥", previous_queries=prev)
    assert out and out not in prev


def test_video_qa_react_uses_semantic_retry_when_insufficient():
    """ReAct 证据不足时，换角度重检索并命中。"""
    from app.agents.video_qa_react import run_video_qa_react_retrieval

    def _fake_tools(messages, tools, **kwargs):
        if any(m.get("role") == "tool" for m in messages):
            return {"tool_call": False, "content": "草稿"}
        return {
            "tool_call": True,
            "tool_calls": [{
                "tool_call_id": "c1",
                "tool_name": "search_video_chunks",
                "arguments": {"question": "讲了啥", "top_k": 5},
            }],
            "content": "",
        }

    calls = []

    def _fake_search(session_id, video_id, query, title, tags, top_k):
        calls.append(query)
        if "主题" in query:
            return [{"content": "命中内容", "score": 0.9, "video_id": "v1"}], True
        return [{"content": "弱相关", "score": 0.01, "video_id": "v1"}], False

    with patch("app.config.settings.video_qa_react_enabled", True), \
         patch("app.config.settings.video_qa_react_max_steps", 2), \
         patch("app.config.settings.video_qa_semantic_retry_enabled", True), \
         patch("app.config.settings.video_qa_semantic_retry_max", 1), \
         patch("app.agents.video_qa_react.LLM_tools.chat_with_tools", side_effect=_fake_tools), \
         patch("app.agents.video_qa_react._execute_search_tool", side_effect=_fake_search), \
         patch("app.agents.semantic_retry.reformulate_query", return_value="主题 内容 简介"):
        knowledge, sufficient, _steps, _note, _stop = run_video_qa_react_retrieval(
            video_id="v1", question="讲了啥", title="教程", tags="py", session_id="s1",
        )
    assert sufficient is True
    assert any("主题" in c for c in calls)
    assert len(knowledge) >= 1

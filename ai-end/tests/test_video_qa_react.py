"""Video QA Bounded ReAct 与演示模式路径对齐测试。"""
from unittest.mock import patch

from app.agents.video_qa_react import run_video_qa_react_retrieval
from app.harness.llm_replay import replay_query_rewrite, replay_video_qa_react_step


def test_replay_query_rewrite_expands_colloquial():
    with patch("app.harness.llm_replay.replay_enabled", return_value=True):
        out = replay_query_rewrite("这个讲了啥", title="Python教程", tags="编程")
    assert "讲了什么" in out or "讲了啥" in out
    assert "Python教程" in out


def test_replay_video_qa_react_two_step():
    with patch("app.harness.llm_replay.replay_enabled", return_value=True):
        step1 = replay_video_qa_react_step(
            [{"role": "user", "content": "video_id: v1\n用户问题: 讲了什么"}],
        )
        assert step1["tool_call"] is True
        assert step1["tool_name"] == "search_video_chunks"

        step2 = replay_video_qa_react_step(
            [
                {"role": "user", "content": "用户问题: 讲了什么"},
                {"role": "tool", "content": "[1] Python 语法"},
            ],
        )
        assert step2["tool_call"] is False
        assert step2["content"]


def test_bounded_react_executes_tool_then_finishes():
    hits = [{"content": "Python 入门", "score": 0.9, "video_id": "v1"}]

    def _fake_tools(messages, tools, **kwargs):
        if any(m.get("role") == "tool" for m in messages):
            return {"tool_call": False, "content": "草稿[1]"}
        return {
            "tool_call": True,
            "tool_calls": [{
                "tool_call_id": "c1",
                "tool_name": "search_video_chunks",
                "arguments": {"question": "讲了什么", "top_k": 5},
            }],
            "content": "",
        }

    with patch("app.config.settings.video_qa_react_enabled", True), \
         patch("app.config.settings.video_qa_react_max_steps", 3), \
         patch("app.config.settings.video_qa_react_stop_on_sufficient", False), \
         patch("app.agents.video_qa_react.LLM_tools.chat_with_tools", side_effect=_fake_tools), \
         patch(
             "app.agents.video_qa_react._execute_search_tool",
             return_value=(hits, True),
         ):
        knowledge, sufficient, steps, note, stop = run_video_qa_react_retrieval(
            video_id="v1",
            question="讲了什么",
            title="教程",
            tags="py",
            session_id="s1",
        )
    assert len(knowledge) == 1
    assert sufficient is True
    assert steps == 2  # 关闭早停时，模型仍会走第二步给出草稿
    assert note == "草稿[1]"


def test_bounded_react_stops_early_when_sufficient_by_default():
    """默认开启 stop_on_sufficient：证据充足即停在第 1 步，不再多检索一轮。"""
    hits = [{"content": "命中", "score": 0.9, "video_id": "v1"}]

    def _fake_tools(messages, tools, **kwargs):
        return {
            "tool_call": True,
            "tool_calls": [{
                "tool_call_id": "c1",
                "tool_name": "search_video_chunks",
                "arguments": {"question": "讲了什么", "top_k": 5},
            }],
            "content": "",
        }

    with patch("app.config.settings.video_qa_react_enabled", True), \
         patch("app.config.settings.video_qa_react_max_steps", 3), \
         patch("app.config.settings.video_qa_semantic_retry_enabled", False), \
         patch("app.agents.video_qa_react.LLM_tools.chat_with_tools", side_effect=_fake_tools), \
         patch("app.agents.video_qa_react._execute_search_tool", return_value=(hits, True)):
        _k, sufficient, steps, _note, stop = run_video_qa_react_retrieval(
            video_id="v1", question="讲了什么", title="教程", tags="py", session_id="s1",
        )
    assert sufficient is True
    assert stop == "sufficient"
    assert steps == 1


def test_demo_mode_keeps_rewrite_enabled():
    from app.config import Settings

    s = Settings(demo_mode=True, video_qa_llm_rewrite=True, video_qa_llm_grounding=True)
    assert s.effective_video_qa_llm_rewrite is True
    assert s.effective_video_qa_llm_grounding is True
    assert s.effective_llm_replay_enabled is True


def test_rewrite_uses_replay_in_demo_mode():
    from app.tools.video_qa_retrieval import rewrite_video_qa_query

    with patch("app.config.settings.demo_mode", True), \
         patch("app.config.settings.video_qa_llm_rewrite", True), \
         patch("app.harness.llm_replay.replay_query_rewrite", return_value="讲了什么 主题 Python教程"):
        out = rewrite_video_qa_query("讲了啥", title="Python教程", tags="py")
    assert "讲了什么" in out or "Python教程" in out


def test_bounded_react_nudges_then_stops_on_duplicate_search():
    """模型反复用相同 query 检索：先 nudge 换角度，连续重复超阈才强制终止。"""
    low_hits = [{"content": "弱相关", "score": 0.01, "video_id": "v1"}]

    def _looping_tools(messages, tools, **kwargs):
        return {
            "tool_call": True,
            "tool_calls": [{
                "tool_call_id": "c1",
                "tool_name": "search_video_chunks",
                "arguments": {"question": "讲了什么", "top_k": 5},
            }],
            "content": "",
        }

    calls = []

    def _fake_search(session_id, video_id, query, title, tags, top_k):
        calls.append(query)
        return low_hits, False

    with patch("app.config.settings.video_qa_react_enabled", True), \
         patch("app.config.settings.video_qa_react_max_steps", 5), \
         patch("app.config.settings.video_qa_semantic_retry_enabled", False), \
         patch("app.agents.video_qa_react.LLM_tools.chat_with_tools", side_effect=_looping_tools), \
         patch("app.agents.video_qa_react._execute_search_tool", side_effect=_fake_search):
        knowledge, sufficient, steps, _note, stop_reason = run_video_qa_react_retrieval(
            video_id="v1",
            question="讲了什么",
            title="教程",
            tags="py",
            session_id="s1",
        )
    assert len(calls) == 1  # 重复调用不再真正执行工具
    assert stop_reason == "duplicate_repeat"
    assert steps == 3  # 第 1 次重复 nudge，第 2 次重复强制停
    assert sufficient is False


def test_bounded_react_allows_distinct_queries():
    """不同 query 不算重复，应正常执行多步。"""
    def _seq_tools(messages, tools, **kwargs):
        done = sum(1 for m in messages if m.get("role") == "tool")
        if done >= 2:
            return {"tool_call": False, "content": "草稿"}
        return {
            "tool_call": True,
            "tool_calls": [{
                "tool_call_id": f"c{done}",
                "tool_name": "search_video_chunks",
                "arguments": {"question": f"关键词{done}", "top_k": 5},
            }],
            "content": "",
        }

    calls = []

    def _fake_search(session_id, video_id, query, title, tags, top_k):
        calls.append(query)
        return [{"content": f"内容{query}", "score": 0.1, "video_id": "v1"}], False

    with patch("app.config.settings.video_qa_react_enabled", True), \
         patch("app.config.settings.video_qa_react_max_steps", 5), \
         patch("app.config.settings.video_qa_semantic_retry_enabled", False), \
         patch("app.agents.video_qa_react.LLM_tools.chat_with_tools", side_effect=_seq_tools), \
         patch("app.agents.video_qa_react._execute_search_tool", side_effect=_fake_search):
        _knowledge, _sufficient, steps, _note, _stop = run_video_qa_react_retrieval(
            video_id="v1",
            question="讲了什么",
            title="教程",
            tags="py",
            session_id="s1",
        )
    assert calls == ["关键词0", "关键词1"]
    assert steps == 3


def test_bounded_react_stop_on_sufficient_opt_in():
    """开启 stop_on_sufficient 后，证据充足即停在第一步（省一次 LLM 调用）。"""
    hits = [{"content": "命中", "score": 0.9, "video_id": "v1"}]

    def _fake_tools(messages, tools, **kwargs):
        return {
            "tool_call": True,
            "tool_calls": [{
                "tool_call_id": "c1",
                "tool_name": "search_video_chunks",
                "arguments": {"question": "讲了什么", "top_k": 5},
            }],
            "content": "",
        }

    with patch("app.config.settings.video_qa_react_enabled", True), \
         patch("app.config.settings.video_qa_react_max_steps", 3), \
         patch("app.config.settings.video_qa_react_stop_on_sufficient", True), \
         patch("app.config.settings.video_qa_semantic_retry_enabled", False), \
         patch("app.agents.video_qa_react.LLM_tools.chat_with_tools", side_effect=_fake_tools), \
         patch("app.agents.video_qa_react._execute_search_tool", return_value=(hits, True)):
        _k, sufficient, steps, _note, stop_reason = run_video_qa_react_retrieval(
            video_id="v1", question="讲了什么", title="教程", tags="py", session_id="s1",
        )
    assert sufficient is True
    assert stop_reason == "sufficient"
    assert steps == 1

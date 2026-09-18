"""显式 Chain-of-Thought（CoT）测试：解析容错、replay、路由集成。"""
from unittest.mock import patch

from app.agents.cot import CoTResult, parse_cot_response, run_intent_cot
from app.agents.workflows.constants import WorkflowType


class TestParseCoTResponse:
    def test_parses_reasoning_and_conclusion(self):
        text = (
            "用户问的是视频内容。\n"
            "问题包含「这个视频」，指向当前视频。\n"
            f"结论：{WorkflowType.VIDEO_QA}"
        )
        result = parse_cot_response(text, list(WorkflowType.all()))
        assert result is not None
        assert result.intent == WorkflowType.VIDEO_QA
        assert "视频内容" in result.reasoning
        assert "结论" not in result.reasoning

    def test_parses_english_colon(self):
        text = f"分析：用户想找视频。\n结论: {WorkflowType.RECOMMEND}"
        result = parse_cot_response(text, list(WorkflowType.all()))
        assert result is not None
        assert result.intent == WorkflowType.RECOMMEND

    def test_falls_back_to_contains(self):
        text = f"我觉得这属于 {WorkflowType.CHAT} 类型"
        result = parse_cot_response(text, list(WorkflowType.all()))
        assert result is not None
        assert result.intent == WorkflowType.CHAT

    def test_returns_none_when_no_intent(self):
        assert parse_cot_response("完全无关的一段话", list(WorkflowType.all())) is None

    def test_returns_none_on_empty(self):
        assert parse_cot_response("", list(WorkflowType.all())) is None
        assert parse_cot_response("x", []) is None


class TestRunIntentCoT:
    def test_none_when_question_empty(self):
        assert run_intent_cot("", list(WorkflowType.all())) is None
        assert run_intent_cot("q", []) is None

    def test_replay_returns_structured_result(self):
        with patch("app.config.settings.llm_replay_enabled", True):
            result = run_intent_cot("推荐一些好看的视频", list(WorkflowType.all()))
        assert isinstance(result, CoTResult)
        assert result.intent in WorkflowType.all()
        assert result.reasoning

    def test_llm_failure_returns_none(self):
        with patch("app.config.settings.llm_replay_enabled", False), \
             patch("app.tools.llm_tools.LLM_tools.chat_sync", side_effect=RuntimeError("boom")):
            assert run_intent_cot("随便问问", list(WorkflowType.all())) is None


class TestRouterCoTIntegration:
    def test_route_with_llm_returns_cot_method(self):
        from app.agents.router import Router
        router = Router()
        with patch("app.config.settings.router_cot_enabled", True), \
             patch("app.config.settings.llm_replay_enabled", True):
            step = router._route_with_llm("推荐一些好看的视频", {})
        assert step is not None
        intent, method = step
        assert method == "cot"
        assert intent in WorkflowType.all()

    def test_route_with_llm_falls_back_to_tool_call(self):
        from app.agents.router import Router
        router = Router()
        fake = {
            "tool_call": True,
            "arguments": {"intent_type": WorkflowType.USER_DATA},
        }
        with patch("app.config.settings.router_cot_enabled", False), \
             patch("app.tools.llm_tools.LLM_tools.chat_with_tools_router", return_value=fake):
            step = router._route_with_llm("我点赞了哪些视频", {})
        assert step == (WorkflowType.USER_DATA, "tool_call")

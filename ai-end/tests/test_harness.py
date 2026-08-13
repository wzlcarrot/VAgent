import pytest
from unittest.mock import patch, MagicMock



class TestToolSandbox:
    """工具沙箱校验：deny by default + 白名单 + public 显式放行"""

    def setup_method(self):
        from app.tools.tool_registry import ToolRegistry, Tool
        self.registry = ToolRegistry()
        self._saved = dict(self.registry._tools)
        self.registry._tools.clear()
        self.tool_restricted = Tool(
            name="tool_restricted",
            description="restricted",
            parameters={},
            allowed_agents=["video_qa_workflow"],
        )
        self.tool_public = Tool(
            name="tool_public",
            description="public",
            parameters={},
            public=True,
        )
        self.tool_empty = Tool(
            name="tool_empty",
            description="no whitelist, no public",
            parameters={},
            allowed_agents=[],
        )
        self.registry.register(self.tool_restricted)
        self.registry.register(self.tool_public)
        self.registry.register(self.tool_empty)

    def teardown_method(self):
        from app.tools.tool_registry import ToolRegistry
        reg = ToolRegistry()
        reg._tools.clear()
        reg._tools.update(self._saved)

    def test_nonexistent_tool_denied(self):
        from app.tools.tool_registry import ToolSandbox
        assert ToolSandbox.validate_call("does_not_exist", "video_qa_workflow") is False

    def test_restricted_tool_allowed_for_listed_agent(self):
        from app.tools.tool_registry import ToolSandbox
        assert ToolSandbox.validate_call("tool_restricted", "video_qa_workflow") is True

    def test_restricted_tool_denied_for_other_agent(self):
        from app.tools.tool_registry import ToolSandbox
        assert ToolSandbox.validate_call("tool_restricted", "chat_workflow") is False

    def test_public_tool_allowed_for_any_agent(self):
        from app.tools.tool_registry import ToolSandbox
        assert ToolSandbox.validate_call("tool_public", "any_agent_at_all") is True

    def test_empty_whitelist_denied_by_default(self):
        """核心 bug 修复：没有 allowed_agents 也没有 public 标记的工具必须拒绝"""
        from app.tools.tool_registry import ToolSandbox
        assert ToolSandbox.validate_call("tool_empty", "video_qa_workflow") is False
        assert ToolSandbox.validate_call("tool_empty", "router") is False


class TestToolGovernorSandboxIntegration:
    """ToolGovernor.gate() 必须执行沙箱校验，拒绝时不消耗 rate limit 配额"""

    def test_gate_rejects_sandbox_violation(self):
        from app.harness.tool_governor import ToolGovernor, ToolAccessDenied
        from app.tools.tool_registry import ToolRegistry, Tool, ToolSandbox

        reg = ToolRegistry()
        saved = dict(reg._tools)
        reg._tools.clear()
        reg.register(Tool(
            name="qa_only_tool",
            description="",
            parameters={},
            allowed_agents=["video_qa_workflow"],
        ))

        try:
            gov = ToolGovernor()
            gov.reset_session("sandbox_test_session")

            with __import__("pytest").raises(ToolAccessDenied):
                gov.gate(
                    session_id="sandbox_test_session",
                    agent="user_data_workflow",
                    tool_name="qa_only_tool",
                    arguments={},
                    execute_fn=lambda: "should not run",
                    record_artifact=False,
                )
            # 关键断言：拒绝后该 session 的计数没有增加
            assert gov.get_call_count("sandbox_test_session", "qa_only_tool") == 0
        finally:
            reg._tools.clear()
            reg._tools.update(saved)

    def test_gate_allows_listed_agent(self):
        from app.harness.tool_governor import ToolGovernor
        from app.tools.tool_registry import ToolRegistry, Tool

        reg = ToolRegistry()
        saved = dict(reg._tools)
        reg._tools.clear()
        reg.register(Tool(
            name="qa_only_tool_2",
            description="",
            parameters={},
            allowed_agents=["video_qa_workflow"],
        ))

        try:
            gov = ToolGovernor()
            gov.reset_session("sandbox_test_session_2")
            result = gov.gate(
                session_id="sandbox_test_session_2",
                agent="video_qa_workflow",
                tool_name="qa_only_tool_2",
                arguments={},
                execute_fn=lambda: "ok",
                record_artifact=False,
            )
            assert result == "ok"
            assert gov.get_call_count("sandbox_test_session_2", "qa_only_tool_2") == 1
        finally:
            reg._tools.clear()
            reg._tools.update(saved)


class TestLLMRaceConditionFix:
    """验证 chat_with_tools_router 不再修改全局 settings.llm_provider"""

    def test_router_does_not_mutate_global_settings(self):
        """核心 bug 修复：调用 chat_with_tools_router 后全局 settings.llm_provider 保持不变"""
        from app.config import settings
        from app.tools.llm_tools import LLM_tools
        from unittest.mock import patch, MagicMock

        original_provider = settings.llm_provider
        original_router_provider = settings.router_llm_provider
        try:
            settings.router_llm_provider = "minimax"
            settings.llm_provider = "deepseek"

            with patch.object(LLM_tools, "chat_with_tools", return_value={"content": "ok"}) as mock:
                # 调用 router 专用入口
                LLM_tools.chat_with_tools_router([], [])
                # 关键断言：全局 settings.llm_provider 没有被改
                assert settings.llm_provider == "deepseek", (
                    f"全局 settings.llm_provider 被改成了 {settings.llm_provider}，"
                    f"这会导致多线程下 router 用 minimax 模型，普通用 deepseek 模型的串台"
                )
                # 验证 chat_with_tools 收到的是 provider 参数
                call_kwargs = mock.call_args.kwargs
                assert call_kwargs.get("provider") == "minimax"
        finally:
            settings.llm_provider = original_provider
            settings.router_llm_provider = original_router_provider

    def test_resolve_provider_does_not_touch_settings(self):
        """_resolve_provider 应该是纯函数，只读 settings 不写"""
        from app.config import settings
        from app.tools.llm_tools import _resolve_provider
        original = settings.llm_provider
        try:
            settings.llm_provider = "deepseek"
            base_url, model, api_key = _resolve_provider()
            assert "deepseek" in base_url.lower() or "deepseek" in model.lower()
            assert settings.llm_provider == "deepseek"

            base_url2, model2, api_key2 = _resolve_provider("minimax")
            assert "minimax" in model2.lower() or "minimax" in base_url2.lower()
            # 关键：调用 _resolve_provider 不会修改 settings
            assert settings.llm_provider == "deepseek"
        finally:
            settings.llm_provider = original


class TestRedisCircuitBreaker:
    """验证 Redis 熔断器：失败时熔断、冷却期内不重连、冷却后允许重试"""

    @pytest.fixture(autouse=True)
    def _restore_redis_globals(self):
        """保存/恢复 context_tools 全局 Redis 状态，防止污染其他测试"""
        import app.tools.context_tools as ct
        saved = (ct._redis_client, ct._redis_circuit_open, ct._last_redis_failure)
        yield
        ct._redis_client, ct._redis_circuit_open, ct._last_redis_failure = saved

    def test_circuit_opens_after_failure(self):
        import app.tools.context_tools as ct
        # 重置熔断器
        ct._redis_circuit_open = False
        ct._last_redis_failure = 0.0
        ct._redis_client = None

        # 模拟 redis 不可用：注入一个 ping 抛异常的客户端
        fake_client = MagicMock()
        fake_client.ping.side_effect = Exception("connection refused")
        with patch("redis.Redis", return_value=fake_client):
            result = ct._get_redis()
            assert result is None
            assert ct._redis_circuit_open is True
            assert ct._last_redis_failure > 0

    def test_circuit_short_circuits_during_cooldown(self):
        """熔断开启 + 冷却期内：不应尝试连接，直接返回 None"""
        import app.tools.context_tools as ct
        import time as _time
        ct._redis_circuit_open = True
        ct._last_redis_failure = _time.time()  # 刚刚失败
        ct._redis_client = None

        # 即便 redis 恢复可用，冷却期内不应尝试连接
        with patch("redis.Redis") as mock_redis:
            result = ct._get_redis()
            assert result is None
            assert mock_redis.call_count == 0, "冷却期内不应调用 redis.Redis()"

    def test_circuit_half_opens_after_cooldown(self):
        """冷却期过后：允许一次重试"""
        import app.tools.context_tools as ct
        import time as _time
        ct._redis_circuit_open = True
        ct._last_redis_failure = _time.time() - 10.0  # 10 秒前失败
        ct._redis_client = None

        # 模拟恢复：ping 成功
        fake_client = MagicMock()
        fake_client.ping.return_value = True
        with patch("redis.Redis", return_value=fake_client):
            result = ct._get_redis()
            assert result is fake_client
            # 成功后熔断器关闭
            assert ct._redis_circuit_open is False
            assert ct._last_redis_failure == 0.0


class TestInvokeWithGovernorNoneFallback:
    """invoke_with_governor 对 gate 返回 None（hook 拦截）兜底为空结果"""

    def test_none_result_falls_back_to_empty(self):
        from app.agents.workflows.harness_helpers import invoke_with_governor
        from app.agents.workflows.constants import WorkflowType
        with patch("app.agents.workflows.harness_helpers.ToolGovernor") as mock_gov:
            mock_gov.return_value.gate.return_value = None  # 模拟 before hook 拦截
            result = invoke_with_governor(
                "session_1", WorkflowType.CHAT, "retrieve_knowledge", lambda: "should_not_run"
            )
        assert result == []  # None → 兜底空列表，不破坏 workflow

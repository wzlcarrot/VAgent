"""
Hook 引擎测试：注册/触发/拦截/enabled 开关/审计钩子
"""
import pytest
from app.harness.hooks import HooksManager, HookEvent


@pytest.fixture()
def mgr():
    return HooksManager()


class TestHooksManager:
    def test_register_unknown_event_warns(self, mgr):
        mgr.register("not_a_real_event", lambda ctx: None)
        assert mgr._hooks.get("not_a_real_event") is None

    def test_trigger_observe(self, mgr):
        seen = []
        mgr.register(HookEvent.AFTER_TOOL_CALL, lambda ctx: seen.append(ctx["tool_name"]))
        mgr.trigger(HookEvent.AFTER_TOOL_CALL, tool_name="retrieve_knowledge", agent="chat")
        assert seen == ["retrieve_knowledge"]

    def test_trigger_merge_context(self, mgr):
        mgr.register(HookEvent.AFTER_MESSAGE, lambda ctx: {"len": len(ctx["content"])})
        ctx = mgr.trigger(HookEvent.AFTER_MESSAGE, content="hello")
        assert ctx["len"] == 5

    def test_intercept_deny(self, mgr):
        mgr.register(HookEvent.BEFORE_TOOL_CALL, lambda ctx: False)
        assert mgr.trigger_intercept(HookEvent.BEFORE_TOOL_CALL, tool_name="x") is False

    def test_intercept_allow(self, mgr):
        mgr.register(HookEvent.BEFORE_TOOL_CALL, lambda ctx: True)
        assert mgr.trigger_intercept(HookEvent.BEFORE_TOOL_CALL, tool_name="x") is True

    def test_intercept_no_hooks_allows(self, mgr):
        assert mgr.trigger_intercept(HookEvent.BEFORE_TOOL_CALL) is True

    def test_disabled_manager_skips_hooks(self):
        mgr = HooksManager(enabled=False)
        called = []
        mgr.register(HookEvent.AFTER_TOOL_CALL, lambda ctx: called.append(1))
        mgr.trigger(HookEvent.AFTER_TOOL_CALL)
        assert called == []

    def test_disabled_intercept_allows(self):
        mgr = HooksManager(enabled=False)
        mgr.register(HookEvent.BEFORE_TOOL_CALL, lambda ctx: False)
        assert mgr.trigger_intercept(HookEvent.BEFORE_TOOL_CALL) is True

    def test_hook_exception_does_not_break(self, mgr):
        mgr.register(HookEvent.AFTER_TOOL_CALL, lambda ctx: (_ for _ in ()).throw(RuntimeError("boom")))
        # 钩子异常被捕获，不影响主流程
        ctx = mgr.trigger(HookEvent.AFTER_TOOL_CALL, tool_name="x")
        assert ctx["tool_name"] == "x"

    def test_event_all_contains_all(self):
        assert set(HookEvent.all()) == {
            "before_tool_call", "after_tool_call", "before_message", "after_message",
        }

"""轻量 middleware / waterfall 扩展点（借鉴 deepseek-harness）。"""
from unittest.mock import patch

import pytest

from app.harness.middleware import Waterfall, tool_after, tool_before


@pytest.fixture(autouse=True)
def _clean_middleware():
    tool_before.clear()
    tool_after.clear()
    yield
    tool_before.clear()
    tool_after.clear()


def test_waterfall_passthrough():
    w = Waterfall("x")
    assert w.run({}, lambda: "ok") == "ok"


def test_waterfall_wraps_in_order():
    w = Waterfall("x")
    order = []

    def a(payload, nxt):
        order.append("a-before")
        r = nxt()
        order.append("a-after")
        return r

    def b(payload, nxt):
        order.append("b")
        return nxt()

    w.use(a)
    w.use(b)
    out = w.run({}, lambda: (order.append("terminal"), "R")[1])
    assert out == "R"
    assert order == ["a-before", "b", "terminal", "a-after"]


def test_waterfall_short_circuit():
    w = Waterfall("x")

    def block(payload, nxt):
        return "blocked"

    w.use(block)
    called = []
    assert w.run({}, lambda: called.append(1)) == "blocked"
    assert called == []


def test_gate_tool_after_transforms_result():
    from app.harness.tool_governor import ToolGovernor

    def redact(payload, nxt):
        r = nxt()
        return r.replace("secret", "***") if isinstance(r, str) else r

    tool_after.use(redact)
    with patch("app.config.settings.harness_enabled", True), \
         patch("app.config.settings.hitl_enabled", False), \
         patch("app.harness.tool_governor._policy_limits", return_value=(5, 10.0, "allow", 100, False)), \
         patch("app.tools.tool_registry.ToolSandbox.validate_call", return_value=True):
        gov = ToolGovernor()
        out = gov.gate("sid", "wf", "t", {}, lambda: "secret data")
    assert out == "*** data"


def test_gate_tool_before_can_short_circuit():
    from app.harness.tool_governor import ToolGovernor

    def block(payload, nxt):
        return "cached"

    tool_before.use(block)
    called = []
    with patch("app.config.settings.harness_enabled", True), \
         patch("app.config.settings.hitl_enabled", False), \
         patch("app.harness.tool_governor._policy_limits", return_value=(5, 10.0, "allow", 100, False)), \
         patch("app.tools.tool_registry.ToolSandbox.validate_call", return_value=True):
        gov = ToolGovernor()
        out = gov.gate("sid", "wf", "t", {}, lambda: called.append(1))
    assert out == "cached"
    assert called == []

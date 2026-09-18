"""工具结果溢出落盘 + 续读提示（借鉴 pi overflow）。"""
from unittest.mock import patch

from app.harness.tool_governor import ToolGovernor


def test_spill_on_truncation(tmp_path):
    big = "x" * 500
    with patch("app.config.settings.harness_enabled", True), \
         patch("app.config.settings.hitl_enabled", False), \
         patch("app.config.settings.tool_result_spill_enabled", True), \
         patch("app.harness.tool_governor._policy_limits", return_value=(5, 10.0, "allow", 50, False)), \
         patch("app.harness.run_trace._trace_root", return_value=tmp_path), \
         patch("app.tools.tool_registry.ToolSandbox.validate_call", return_value=True):
        gov = ToolGovernor()
        out = gov.gate("sid", "wf", "t", {}, lambda: big)

    assert isinstance(out, str)
    assert "完整输出已存" in out
    files = list((tmp_path / "tool_outputs").glob("*.txt"))
    assert files, "完整输出应落盘"
    assert files[0].read_text(encoding="utf-8") == big


def test_no_spill_when_under_limit(tmp_path):
    small = "ok"
    with patch("app.config.settings.harness_enabled", True), \
         patch("app.config.settings.hitl_enabled", False), \
         patch("app.config.settings.tool_result_spill_enabled", True), \
         patch("app.harness.tool_governor._policy_limits", return_value=(5, 10.0, "allow", 100, False)), \
         patch("app.harness.run_trace._trace_root", return_value=tmp_path), \
         patch("app.tools.tool_registry.ToolSandbox.validate_call", return_value=True):
        gov = ToolGovernor()
        out = gov.gate("sid", "wf", "t", {}, lambda: small)

    assert out == "ok"
    assert not (tmp_path / "tool_outputs").exists()

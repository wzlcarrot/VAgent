"""Run Trace 单元测试。"""
from unittest.mock import patch

import pytest


@pytest.fixture
def trace_dir(tmp_path):
    with patch("app.harness.run_trace.settings") as mock_settings:
        mock_settings.trace_enabled = True
        mock_settings.trace_root = str(tmp_path)
        yield tmp_path


class TestRunTrace:
    def test_begin_emit_finish(self, trace_dir):
        from app.harness.run_trace import begin_run, finish_run, read_trace

        handle = begin_run("sess-1", {"question": "hello"})
        assert handle is not None
        handle.emit("route_decision", {"workflow": "chat_workflow"})
        finish_run(status="completed")

        events = read_trace("sess-1", handle.run_id)
        types = [e["type"] for e in events]
        assert "run_start" in types
        assert "route_decision" in types
        assert "run_end" in types

    def test_disabled_returns_none(self):
        with patch("app.harness.run_trace.settings") as mock_settings:
            mock_settings.trace_enabled = False
            from app.harness.run_trace import begin_run
            assert begin_run("s", {}) is None

"""P2 商业化：weekly golden / Trace sessions / 意图三分。"""
from pathlib import Path
from unittest.mock import patch

from app.harness.run_trace import begin_run, finish_run, list_recent_sessions, summarize_run
from app.harness.weekly_golden import append_feedback_case, list_weekly_cases


class TestWeeklyGolden:
    def test_append_and_list(self, tmp_path: Path):
        with patch("app.config.settings.weekly_golden_enabled", True), \
             patch("app.config.settings.weekly_golden_root", str(tmp_path)):
            r = append_feedback_case(
                session_id="s1",
                user_id="u1",
                feedback="not_helpful",
                message_index=0,
                question="这个视频讲了什么",
                answer="不知道",
                workflow_type="video_qa",
            )
            assert r["written"] is True
            data = list_weekly_cases(r["week"])
            assert data["count"] == 1
            assert data["negative"] == 1
            assert data["cases"][0]["question"] == "这个视频讲了什么"


class TestTraceSessions:
    def test_list_recent_after_run(self, tmp_path: Path):
        with patch("app.config.settings.trace_enabled", True), \
             patch("app.config.settings.trace_root", str(tmp_path)):
            h = begin_run("sess_admin", {"question": "hi"})
            assert h is not None
            finish_run(status="completed")
            sessions = list_recent_sessions(10)
            assert any(s["session_id"] == "sess_admin" for s in sessions)
            summary = summarize_run("sess_admin", h.run_id)
            assert summary["found"] is True

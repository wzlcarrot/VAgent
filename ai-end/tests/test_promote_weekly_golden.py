"""promote_weekly_golden 去重与猜测。"""
from pathlib import Path
from unittest.mock import patch

from app.agents.workflows.constants import WorkflowType
from app.harness.weekly_golden import append_feedback_case
from scripts.promote_weekly_golden import candidates_from_week, dedupe, guess_expected, save_promoted


def test_guess_expected():
    assert guess_expected("推荐一些视频") == WorkflowType.RECOMMEND
    assert guess_expected("这个视频讲了什么") == WorkflowType.VIDEO_QA
    assert guess_expected("平台有什么功能") == WorkflowType.CHAT


def test_promote_from_weekly(tmp_path: Path):
    with patch("app.config.settings.weekly_golden_enabled", True), \
         patch("app.config.settings.weekly_golden_root", str(tmp_path / "wg")), \
         patch("scripts.promote_weekly_golden.PROMOTED_PATH", tmp_path / "behavior_promoted.json"):
        append_feedback_case(
            session_id="s1",
            user_id="u1",
            feedback="not_helpful",
            message_index=0,
            question="推荐一些科技视频",
            answer="坏回答",
            workflow_type=WorkflowType.RECOMMEND,
        )
        append_feedback_case(
            session_id="s1",
            user_id="u1",
            feedback="helpful",
            message_index=1,
            question="平台有什么功能",
            answer="好回答",
        )
        cands = candidates_from_week(None, 50)
        assert len(cands) == 1
        assert cands[0]["q"] == "推荐一些科技视频"
        added = dedupe([], cands)
        save_promoted(added)
        data = (tmp_path / "behavior_promoted.json").read_text(encoding="utf-8")
        assert "推荐一些科技视频" in data

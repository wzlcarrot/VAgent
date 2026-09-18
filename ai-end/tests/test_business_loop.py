"""业务闭环：反馈原因 / 推荐点击埋点。"""
from pathlib import Path

from app.harness import recommend_clicks as rc
from app.harness.weekly_golden import append_feedback_case


def test_append_feedback_with_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.harness.weekly_golden._golden_root",
        lambda: Path(tmp_path),
    )
    meta = append_feedback_case(
        session_id="s1",
        user_id="u1",
        feedback="not_helpful",
        message_index=0,
        question="推荐",
        answer="...",
        reason="bad_recommend",
        video_ids=["v1"],
    )
    assert meta["written"] is True
    lines = list(Path(tmp_path).glob("*.jsonl"))
    assert lines
    text = lines[0].read_text(encoding="utf-8")
    assert "bad_recommend" in text


def test_recommend_click_stats(tmp_path, monkeypatch):
    monkeypatch.setattr("app.harness.recommend_clicks._root", lambda: Path(tmp_path))
    r = rc.record_recommend_click(user_id="u1", video_id="vid1", session_id="s")
    assert r["written"] is True
    stats = rc.click_stats(days=7)
    assert stats["clicks_today"] >= 1
    assert stats["clicks_window"] >= 1

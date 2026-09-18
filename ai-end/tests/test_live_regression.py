"""Live 回归剧本解析单测。"""
from pathlib import Path

from app.harness.live_regression import load_live_script, parse_live_script


def test_parse_viewhub_script():
    path = Path(__file__).resolve().parents[1] / "fixtures" / "viewhub_live_turns.properties"
    script = load_live_script(path)
    assert script.anchor == "VH-9001"
    assert len(script.turn_refs) == 15
    t02 = script.turns["t02"]
    assert "科技" in t02.text
    assert "stage=routing" in t02.expect_sse
    t11 = script.turns["t11"]
    assert t11.feedback == "not_helpful"
    assert t11.feedback_videos_from_last is True


def test_parse_minimal():
    text = """
# comment
anchor=ABC
turn.refs=t1
turn.t1.text=hello
turn.t1.expect-any=hi|hello
"""
    script = parse_live_script(text)
    assert script.anchor == "ABC"
    assert script.turns["t1"].expect_any == ["hi", "hello"]

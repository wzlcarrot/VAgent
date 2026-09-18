"""SSE 断言与离线回归。"""
from pathlib import Path

from app.harness.sse_assert import assert_sequence, load_script, match_event, parse_script


def test_match_event_core():
    assert match_event({"type": "status", "stage": "routing"}, "stage=routing")
    assert match_event({"type": "retry", "op": "LLM.chat_sync"}, "retry_op=LLM")
    assert match_event(
        {"type": "tool", "name": "retrieve_knowledge", "status": "start"},
        "tool_start name=retrieve_knowledge",
    )
    assert match_event(
        {"type": "videos", "videos": [{"videoId": "1"}]},
        "videos_min=1",
    )


def test_assert_sequence_ordered():
    events = [
        {"type": "status", "stage": "routing"},
        {"type": "text", "content": "hi"},
        {"type": "status", "stage": "done"},
    ]
    passed, failures = assert_sequence(events, ["stage=routing", "type=text", "stage=done"])
    assert passed == 3 and not failures


def test_parse_mode_offline():
    s = parse_script("# MODE offline\nQUESTION \"q\"\nEXPECT type=text\n")
    assert s.mode == "offline"
    assert s.question == "q"


def test_offline_fixtures_present():
    root = Path(__file__).resolve().parents[1] / "fixtures" / "sse_scripts"
    scripts = list(root.glob("*.txt"))
    assert scripts
    for sp in scripts:
        script = load_script(sp)
        ep = sp.with_suffix(".events.json")
        assert ep.exists(), f"missing events for {sp.name}"
        import json
        events = json.loads(ep.read_text(encoding="utf-8"))
        passed, failures = assert_sequence(events, script.expects)
        assert not failures, (sp.name, failures)
        assert passed == len(script.expects)

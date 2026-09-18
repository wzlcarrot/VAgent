"""event_bridge 与 tool progress 单测。"""
import queue

from app.harness.tool_progress import emit_tool_progress, reset_tool_progress_queue, set_tool_progress_queue
from app.streaming.event_bridge import status_event, tool_event


def test_tool_event_shape():
    evt = tool_event("search_video_chunks", "end", label="检索视频片段", ok=True, duration_ms=12.3)
    assert evt["type"] == "tool"
    assert evt["status"] == "end"
    assert evt["ok"] is True
    assert evt["duration_ms"] == 12.3


def test_emit_tool_progress_queue():
    q: queue.Queue = queue.Queue()
    token = set_tool_progress_queue(q)
    try:
        emit_tool_progress("search_video_chunks", "start")
        emit_tool_progress("search_video_chunks", "end", ok=True, duration_ms=5.0)
        events = [q.get_nowait(), q.get_nowait()]
    finally:
        reset_tool_progress_queue(token)
    assert events[0]["status"] == "start"
    assert events[1]["status"] == "end"
    assert events[1]["duration_ms"] == 5.0


def test_status_event():
    evt = status_event("routing", "分析意图")
    assert evt == {"type": "status", "stage": "routing", "label": "分析意图"}

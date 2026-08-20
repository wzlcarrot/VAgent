import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.workflows.constants import WorkflowType
from app.routers.chat_pipeline import (
    extract_memories_from_conversation,
    parallel_agent_pipeline,
    parse_recommend_count,
    record_streaming,
    record_workflow_request,
    run_workflow_to_result,
)
from app.utils.task_cancel import (
    WorkflowCancelled,
    abort_running_io,
    cancel_scope,
    check_cancelled,
    interruptible_sleep,
    is_cancelled,
    register_abortable,
)


class TestParseRecommendCount:
    def test_default(self):
        assert parse_recommend_count("推荐视频") == 5

    def test_arabic(self):
        assert parse_recommend_count("推荐2个视频") == 2
        assert parse_recommend_count("推荐9条") == 5

    def test_chinese(self):
        assert parse_recommend_count("推荐两个视频") == 2
        assert parse_recommend_count("推荐三个") == 3


class TestTaskCancel:
    def test_not_cancelled_outside_scope(self):
        assert is_cancelled() is False
        check_cancelled()

    def test_cancel_scope_sets_flag(self):
        ev = threading.Event()
        with cancel_scope(ev):
            assert is_cancelled() is False
            ev.set()
            assert is_cancelled() is True
            with pytest.raises(WorkflowCancelled):
                check_cancelled()
        assert is_cancelled() is False

    def test_interruptible_sleep_wakes_on_cancel(self):
        ev = threading.Event()

        def _cancel_soon():
            time.sleep(0.05)
            ev.set()

        threading.Thread(target=_cancel_soon, daemon=True).start()
        t0 = time.time()
        with cancel_scope(ev):
            with pytest.raises(WorkflowCancelled):
                interruptible_sleep(2.0)
        assert time.time() - t0 < 1.0

    def test_abort_running_io_closes_without_waiting(self):
        ev = threading.Event()
        closed = []
        with cancel_scope(ev):
            register_abortable(lambda: closed.append("closed"))
            abort_running_io(ev)
        assert closed == ["closed"]

    def test_executor_timeout_aborts_io(self):
        from app.agents.workflows import run_sync_in_executor

        closed = []

        def work():
            register_abortable(lambda: closed.append(1))
            interruptible_sleep(8)

        async def main():
            with pytest.raises(asyncio.TimeoutError):
                await run_sync_in_executor(work, timeout=0.4)
            await asyncio.sleep(0.05)

        asyncio.run(main())
        assert closed == [1]

    def test_register_after_cancel_runs_immediately(self):
        ev = threading.Event()
        ran = []
        with cancel_scope(ev):
            ev.set()
            register_abortable(lambda: ran.append(1))
        assert ran == [1]


def test_search_empty_pool():
    from app.routers.chat_sessions import search_chat_db
    with patch("app.routers.chat_sessions.get_global_pool", return_value=None):
        assert search_chat_db("u1", "q", 5) == []


def test_extract_skips_empty():
    assert extract_memories_from_conversation("", "q", "a") is None
    assert extract_memories_from_conversation("u", "q", "") is None


def test_record_helpers():
    record_streaming({"type": "text", "content": "x"})
    record_workflow_request(WorkflowType.CHAT)
    record_workflow_request("unknown_wf")


def test_run_workflow_requires_ids():
    r = asyncio.run(run_workflow_to_result(WorkflowType.VIDEO_QA, "这个视频讲什么"))
    assert r["confidence"] == 0.0
    r2 = asyncio.run(run_workflow_to_result(WorkflowType.RECOMMEND, "推荐", user_id=None))
    assert r2["answer"] == ""
    r3 = asyncio.run(run_workflow_to_result(WorkflowType.USER_DATA, "我的点赞", user_id=None))
    assert r3["answer"] == ""


def test_pipeline_chat_text():
    async def collect():
        events = []
        async for e in parallel_agent_pipeline(WorkflowType.CHAT, "你好"):
            events.append(e)
        return events

    with patch(
        "app.routers.chat_pipeline.run_workflow_to_result",
        new_callable=AsyncMock,
        return_value={
            "workflow_type": WorkflowType.CHAT,
            "answer": "hello",
            "confidence": 0.9,
            "recommended_videos": [],
            "reasons": [],
        },
    ):
        events = asyncio.run(collect())
    assert any(e.get("type") == "text" and e.get("content") == "hello" for e in events)
    assert events[-1]["type"] == "status"


def test_pipeline_recommend_fallback_meta():
    route = SimpleNamespace(
        workflow_type=WorkflowType.RECOMMEND,
        confidence=0.8,
        method="hybrid",
    )

    async def fake_run(wf, *args, **kwargs):
        if wf == WorkflowType.RECOMMEND:
            return {
                "workflow_type": wf,
                "answer": "",
                "confidence": 0.0,
                "recommended_videos": [],
                "reasons": [],
            }
        return {
            "workflow_type": WorkflowType.CHAT,
            "answer": "兜底回答",
            "confidence": 0.5,
            "recommended_videos": [],
            "reasons": [],
        }

    async def collect():
        events = []
        async for e in parallel_agent_pipeline(
            WorkflowType.RECOMMEND, "推荐视频", user_id="u1", route_decision=route,
        ):
            events.append(e)
        return events

    with patch("app.routers.chat_pipeline.run_workflow_to_result", side_effect=fake_run):
        events = asyncio.run(collect())
    metas = [e for e in events if e.get("type") == "meta"]
    assert metas
    assert any(e.get("content") == "兜底回答" for e in events)


def test_pipeline_all_failed():
    async def boom(*args, **kwargs):
        raise RuntimeError("down")

    async def collect():
        events = []
        async for e in parallel_agent_pipeline(WorkflowType.CHAT, "hi"):
            events.append(e)
        return events

    with patch("app.routers.chat_pipeline.run_workflow_to_result", side_effect=boom):
        events = asyncio.run(collect())
    assert any(e.get("type") == "text" for e in events)


def test_invoke_skipped_when_cancelled():
    from app.agents.workflows.harness_helpers import invoke_with_governor
    called = []
    ev = threading.Event()
    with cancel_scope(ev):
        ev.set()
        result = invoke_with_governor("sid", "chat_workflow", "search", lambda: called.append(1) or "x")
    assert result == []
    assert called == []


def test_run_chat_workflow_path():
    with patch(
        "app.agents.workflows.run_sync_in_executor",
        new=AsyncMock(return_value={"answer": "ok", "llm_messages": ["m"]}),
    ):
        r = asyncio.run(run_workflow_to_result(WorkflowType.CHAT, "hi"))
    assert r["answer"] == "ok"
    assert r["llm_messages"] == ["m"]


def test_run_workflow_timeout():
    async def boom(*args, **kwargs):
        raise asyncio.TimeoutError()

    with patch("app.agents.workflows.run_sync_in_executor", side_effect=boom):
        r = asyncio.run(run_workflow_to_result(WorkflowType.CHAT, "hi"))
    assert r["confidence"] == 0.0
    assert r["answer"] == ""


def test_get_cursor_no_pool():
    from app.tools.db.cursor import get_cursor
    with patch("app.tools.db.cursor.get_global_pool", return_value=None):
        with get_cursor() as cursor:
            assert cursor is None


def test_get_cursor_abort_cancels_conn():
    from unittest.mock import MagicMock

    from app.tools.db.cursor import get_cursor

    cancelled = []
    conn = MagicMock()
    conn.cancel = lambda: cancelled.append(1)
    conn.cursor.return_value = MagicMock()
    pool = MagicMock()
    pool.getconn.return_value = conn
    ev = threading.Event()
    with patch("app.tools.db.cursor.get_global_pool", return_value=pool):
        with cancel_scope(ev):
            with get_cursor() as cursor:
                assert cursor is not None
                abort_running_io(ev)
    assert cancelled == [1]


def test_collect_checkpoint_steps():
    from unittest.mock import MagicMock

    from app.routers.chat_sessions import collect_checkpoint_steps

    last = SimpleNamespace(step_name="faq", created_at="t0")
    mgr = MagicMock()
    mgr.list_step_details.side_effect = lambda sid, wf: [{"name": "faq"}] if wf == WorkflowType.CHAT else []
    mgr.get_last_completed.return_value = last
    with patch("app.harness.checkpoint.CheckpointManager", return_value=mgr):
        steps = collect_checkpoint_steps("sid")
    assert steps
    assert steps[0]["last_completed_step"] == "faq"


def test_search_chat_db_snippet():
    from unittest.mock import MagicMock

    from app.routers.chat_sessions import search_chat_db

    row = {
        "session_id": "s1",
        "question": "hello world",
        "answer": "prefix hello suffix",
        "created_at": "t",
    }
    cursor = MagicMock()
    cursor.fetchall.return_value = [row]
    conn = MagicMock()
    conn.cursor.return_value = cursor
    pool = MagicMock()
    pool.getconn.return_value = conn
    with patch("app.routers.chat_sessions.get_global_pool", return_value=pool):
        results = search_chat_db("u", "hello", 5)
    assert results[0]["session_id"] == "s1"
    assert results[0]["matched_in"] in ("question", "answer")



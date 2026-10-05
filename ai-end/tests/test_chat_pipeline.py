"""chat_pipeline SSE 序列单测：tool start/end、citations。"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import patch

from app.agents.workflows.constants import WorkflowType
from app.routers.chat_pipeline import parallel_agent_pipeline


def _collect(wf_type: str, question: str, **kwargs):
    async def _run():
        events = []
        async for evt in parallel_agent_pipeline(wf_type, question, **kwargs):
            events.append(evt)
        return events

    return asyncio.run(_run())


def _tool_events(events: list[dict]) -> list[dict]:
    return [e for e in events if e.get("type") == "tool"]


class TestChatPipelineToolSse:
    def test_drains_tool_start_end_from_progress_queue(self):
        route = SimpleNamespace(
            workflow_type=WorkflowType.CHAT,
            confidence=0.9,
            method="consensus",
        )

        async def fake_run(wf, *args, **kwargs):
            from app.harness.tool_progress import emit_tool_progress

            emit_tool_progress("retrieve_knowledge", "start")
            time.sleep(0.02)
            emit_tool_progress("retrieve_knowledge", "end", ok=True, duration_ms=12.5)
            return {
                "workflow_type": WorkflowType.CHAT,
                "answer": "平台支持投稿与 AI 助手。",
                "confidence": 0.9,
                "recommended_videos": [],
                "reasons": [],
            }

        with patch("app.routers.chat_pipeline.run_workflow_to_result", side_effect=fake_run):
            events = _collect(
                WorkflowType.CHAT,
                "平台有什么功能",
                route_decision=route,
            )

        tools = _tool_events(events)
        assert len(tools) >= 2, f"expected tool events, got {tools!r}"
        start = next(e for e in tools if e.get("status") == "start")
        end = next(e for e in tools if e.get("status") == "end")
        assert start["name"] == "retrieve_knowledge"
        assert end["name"] == "retrieve_knowledge"
        assert end.get("ok") is True
        assert end.get("duration_ms") == 12.5
        start_idx = events.index(start)
        end_idx = events.index(end)
        assert start_idx < end_idx

    def test_tool_start_precedes_parallel_status_when_slow(self):
        """工具 emit 发生在 gather 期间，应出现在 parallel 前后均可被 drain。"""

        async def fake_run(wf, *args, **kwargs):
            from app.harness.tool_progress import emit_tool_progress

            emit_tool_progress("dual_recall_and_rerank", "start")
            await asyncio.sleep(0.05)
            emit_tool_progress("dual_recall_and_rerank", "end", ok=True, duration_ms=50.0)
            return {
                "workflow_type": wf,
                "answer": "ok",
                "confidence": 0.8,
                "recommended_videos": [],
                "reasons": [],
            }

        with patch("app.routers.chat_pipeline.run_workflow_to_result", side_effect=fake_run):
            events = _collect(WorkflowType.CHAT, "你好")

        tools = _tool_events(events)
        assert any(e.get("status") == "start" for e in tools)
        assert any(e.get("status") == "end" and e.get("duration_ms") == 50.0 for e in tools)
        stages = [e.get("stage") for e in events if e.get("type") == "status"]
        assert "generating" in stages
        assert stages[-1] == "done"


class TestChatPipelineCitationsSse:
    def test_video_qa_winner_emits_citations(self):
        route = SimpleNamespace(
            workflow_type=WorkflowType.VIDEO_QA,
            confidence=0.85,
            method="consensus",
        )
        citations = [{"id": 1, "snippet": "Python 入门语法", "score": 0.9, "video_id": "v1"}]

        async def fake_run(wf, *args, **kwargs):
            if wf == WorkflowType.VIDEO_QA:
                return {
                    "workflow_type": wf,
                    "answer": "本视频讲解 Python 入门[1]。",
                    "confidence": 0.85,
                    "recommended_videos": [],
                    "reasons": [],
                    "citations": citations,
                }
            return {
                "workflow_type": WorkflowType.CHAT,
                "answer": "兜底",
                "confidence": 0.3,
                "recommended_videos": [],
                "reasons": [],
            }

        with patch("app.routers.chat_pipeline.run_workflow_to_result", side_effect=fake_run):
            events = _collect(
                WorkflowType.VIDEO_QA,
                "这个视频讲了什么",
                video_id="v1",
                user_id="u1",
                route_decision=route,
            )

        cite_events = [e for e in events if e.get("type") == "citations"]
        assert cite_events, "video_qa 胜出时应 emit citations 事件"
        assert cite_events[0]["citations"] == citations
        text = "".join(e.get("content", "") for e in events if e.get("type") == "text")
        assert "Python" in text


def test_main_success_does_not_run_chat_fallback():
    route = SimpleNamespace(workflow_type=WorkflowType.VIDEO_QA, confidence=0.9, method="keyword")
    called = []

    async def fake_run(wf, *args, **kwargs):
        called.append(wf)
        return {
            "workflow_type": wf,
            "answer": "基于视频的回答",
            "confidence": 0.9,
            "citations": [{"id": 1, "snippet": "x"}],
        }

    with patch("app.routers.chat_pipeline.run_workflow_to_result", side_effect=fake_run):
        _collect(WorkflowType.VIDEO_QA, "讲了什么", video_id="v1", route_decision=route)
    assert called == [WorkflowType.VIDEO_QA]


def test_chat_with_images_streams_prepared_messages():
    route = SimpleNamespace(workflow_type=WorkflowType.CHAT, confidence=0.9, method="consensus")
    prepared = [
        {"role": "system", "content": "此前用户说过喜欢科幻"},
        {"role": "user", "content": "这张图是什么"},
    ]
    seen = {}

    async def fake_run(wf, *args, **kwargs):
        return {
            "workflow_type": WorkflowType.CHAT,
            "answer": "[context: truncated]",
            "confidence": 0.9,
            "llm_messages": prepared,
        }

    async def fake_stream(messages, image_urls=None, **kwargs):
        seen["messages"] = messages
        seen["image_urls"] = image_urls
        yield "这是一张海报"

    with patch("app.routers.chat_pipeline.run_workflow_to_result", side_effect=fake_run), \
         patch("app.tools.llm_tools.LLM_tools.stream_chat", side_effect=fake_stream):
        events = _collect(
            WorkflowType.CHAT,
            "这张图是什么",
            image_urls=["http://img/a.png"],
            route_decision=route,
        )

    assert seen["messages"] == prepared
    assert seen["image_urls"] == ["http://img/a.png"]
    text = "".join(e.get("content", "") for e in events if e.get("type") == "text")
    assert "这是一张海报" in text
    assert "[context:" not in text


def test_recommend_with_images_keeps_prepared_text_and_sees_image():
    route = SimpleNamespace(workflow_type=WorkflowType.RECOMMEND, confidence=0.9, method="consensus")
    seen = {}

    async def fake_run(wf, *args, **kwargs):
        if wf == WorkflowType.CHAT:
            return {"workflow_type": wf, "answer": "", "confidence": 0.1}
        return {
            "workflow_type": WorkflowType.RECOMMEND,
            "answer": "为你推荐《星际》",
            "confidence": 0.9,
            "recommended_videos": [{"videoId": "v1", "title": "星际"}],
            "reasons": ["因为你看过科幻"],
        }

    async def fake_stream(messages, image_urls=None, **kwargs):
        seen["image_urls"] = image_urls
        seen["user"] = next(m["content"] for m in messages if m["role"] == "user")
        yield "这张图和科幻有关"

    with patch("app.routers.chat_pipeline.run_workflow_to_result", side_effect=fake_run), \
         patch("app.tools.llm_tools.LLM_tools.stream_chat", side_effect=fake_stream):
        events = _collect(
            WorkflowType.RECOMMEND,
            "推荐一个",
            image_urls=["http://img/a.png"],
            route_decision=route,
        )

    assert any(e.get("type") == "videos" for e in events)
    text_events = [e.get("content", "") for e in events if e.get("type") == "text"]
    assert text_events[0] == "为你推荐《星际》"
    assert seen["image_urls"] == ["http://img/a.png"]
    assert "为你推荐《星际》" in seen["user"]
    assert "这张图和科幻有关" in "".join(text_events)


def test_user_data_with_images_keeps_count_and_sees_image():
    route = SimpleNamespace(workflow_type=WorkflowType.USER_DATA, confidence=0.9, method="consensus")
    seen = {}

    async def fake_run(wf, *args, **kwargs):
        if wf == WorkflowType.CHAT:
            return {"workflow_type": wf, "answer": "", "confidence": 0.1}
        return {
            "workflow_type": WorkflowType.USER_DATA,
            "answer": "你共收藏了 3 次",
            "confidence": 0.9,
        }

    async def fake_stream(messages, image_urls=None, **kwargs):
        seen["image_urls"] = image_urls
        yield "这张图是封面"

    with patch("app.routers.chat_pipeline.run_workflow_to_result", side_effect=fake_run), \
         patch("app.tools.llm_tools.LLM_tools.stream_chat", side_effect=fake_stream):
        events = _collect(
            WorkflowType.USER_DATA,
            "核对一下我的收藏",
            image_urls=["http://img/a.png"],
            route_decision=route,
        )

    text_events = [e.get("content", "") for e in events if e.get("type") == "text"]
    assert text_events[0] == "你共收藏了 3 次"
    assert seen["image_urls"] == ["http://img/a.png"]
    assert "这张图是封面" in "".join(text_events)

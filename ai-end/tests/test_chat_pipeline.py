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
        assert "parallel" in stages
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

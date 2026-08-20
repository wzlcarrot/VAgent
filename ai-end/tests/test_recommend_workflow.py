"""
recommend_workflow 单元测试：覆盖推荐流程的各节点纯逻辑 + 断点恢复。

不依赖真实 DB/LLM，mock UserTools/VideoTools/ranker/CheckpointManager。
"""
from unittest.mock import MagicMock, patch

from app.agents.workflows.recommend_workflow import (
    _build_recommend_markdown,
    cold_start_node,
    has_history_router,
    profile_node,
    reason_node,
    resume_recommend_workflow,
    search_node,
    summary_node,
    supervisor_node,
)


def _state(**overrides):
    base = {
        "user_id": "u1",
        "question": "推荐几个视频",
        "session_id": "s1",
        "top_k": 3,
        "user_profile": {},
        "candidate_videos": [],
        "recommended_videos": [],
        "reasons": [],
        "summary": "",
        "answer": "",
        "workflow_type": "recommend",
    }
    base.update(overrides)
    return base


class TestBuildRecommendMarkdown:
    def test_empty_videos(self):
        assert _build_recommend_markdown([]) == ""

    def test_builds_markdown_with_metadata(self):
        videos = [{
            "video_id": "v1", "title": "机器学习入门", "cover": "/ai/media/cover?sourceName=cover/a.jpg",
            "tags": "AI,算法", "author": "老王", "create_time": "2026-08-01 10:00:00", "play_count": 123,
        }]
        md = _build_recommend_markdown(videos, ["算法相关"])
        assert "## 1. 机器学习入门" in md
        assert "![机器学习入门]" in md
        assert "关键词：AI · 算法" in md
        assert "作者：老王" in md
        assert "创建时间：2026-08-01" in md
        assert "播放量：123次" in md
        assert "推荐理由：算法相关" in md

    def test_missing_fields_omitted(self):
        videos = [{"video_id": "v1", "title": "无元数据"}]
        md = _build_recommend_markdown(videos)
        assert "## 1. 无元数据" in md
        assert "作者" not in md


class TestProfileNode:
    def test_no_user_id(self):
        assert profile_node(_state(user_id=None)) == {"user_profile": {}}

    def test_builds_profile(self):
        from app.models import VideoInfo, VideoPlayHistory
        hist = [VideoPlayHistory(video_id="v1", video_name="机器学习"), VideoPlayHistory(video_id="v2", video_name="深度学习")]
        infos = [
            VideoInfo(videoId="v1", videoName="机器学习", tags="AI,算法", categoryId=1),
            VideoInfo(videoId="v2", videoName="深度学习", tags="AI,神经网络", categoryId=1),
            VideoInfo(videoId="f1", videoName="收藏视频", tags="科普", categoryId=2),
        ]
        with patch("app.agents.workflows.recommend_workflow.UserTools.get_play_history", return_value=hist), \
             patch("app.agents.workflows.recommend_workflow.UserTools.get_favorites", return_value=["f1"]), \
             patch("app.agents.workflows.recommend_workflow.UserTools.get_liked_videos", return_value=["l1"]), \
             patch("app.agents.workflows.recommend_workflow.VideoTools.get_video_info_batch", return_value=infos):
            result = profile_node(_state())
        profile = result["user_profile"]
        assert profile["play_count"] == 2
        assert "AI" in profile["favorite_tags"]
        assert "算法" in profile["favorite_tags"]
        assert "1" in profile["favorite_regions"]
        assert profile["watched_video_ids"] == ["v1", "v2"]
        assert profile["liked_video_ids"] == ["l1"]
        assert profile["favorite_video_ids"] == ["f1"]

    def test_builds_profile_when_video_lookup_fails(self):
        from app.models import VideoPlayHistory
        hist = [VideoPlayHistory(video_id="v1", video_name="机器学习")]
        with patch("app.agents.workflows.recommend_workflow.UserTools.get_play_history", return_value=hist), \
             patch("app.agents.workflows.recommend_workflow.UserTools.get_favorites", return_value=[]), \
             patch("app.agents.workflows.recommend_workflow.UserTools.get_liked_videos", return_value=[]), \
             patch("app.agents.workflows.recommend_workflow.VideoTools.get_video_info_batch", return_value=[]):
            result = profile_node(_state())
        profile = result["user_profile"]
        assert profile["watched_video_ids"] == ["v1"]
        assert profile["favorite_tags"] == []


class TestHasHistoryRouter:
    def test_with_history(self):
        assert has_history_router(_state(user_profile={"play_count": 3})) == "search_node"

    def test_no_history(self):
        assert has_history_router(_state(user_profile={"play_count": 0})) == "summary_node"


class TestSearchNode:
    def test_no_tags_no_question(self):
        assert search_node(_state(user_profile={}, question="")) == {"candidate_videos": []}

    def test_searches_and_builds_candidates(self):
        from app.models import VideoInfo
        results = [{"video_id": "v1"}, {"video_id": "v2"}]
        infos = [
            VideoInfo(videoId="v1", videoName="甲", videoCover="cover/x.jpg", nickName="作者", tags="AI", playCount=10),
            VideoInfo(videoId="v2", videoName="乙"),
        ]
        with patch("app.tools.ranker.dual_recall_and_rerank", return_value=results), \
             patch("app.agents.workflows.recommend_workflow.VideoTools.get_video_info_batch", return_value=infos), \
             patch("app.agents.workflows.recommend_workflow.invoke_with_governor", side_effect=lambda *a, **k: a[3]()), \
             patch("app.tools.memory_tools.MemoryTools.recall_memories", return_value=[]), \
             patch("app.tools.memory_tools.MemoryTools.get_negative_feedback_video_ids", return_value=[]):
            result = search_node(_state(top_k=3))
        vids = [v["video_id"] for v in result["candidate_videos"]]
        assert vids == ["v1", "v2"]

    def test_no_candidates(self):
        with patch("app.tools.ranker.dual_recall_and_rerank", return_value=[]), \
             patch("app.agents.workflows.recommend_workflow.invoke_with_governor", side_effect=lambda *a, **k: a[3]()):
            assert search_node(_state(top_k=3)) == {"candidate_videos": []}

    def test_excludes_negative_feedback_videos(self):
        from app.models import VideoInfo
        results = [{"video_id": "v_bad"}, {"video_id": "v_ok"}]
        infos = [
            VideoInfo(videoId="v_ok", videoName="好视频", tags="AI"),
        ]
        with patch("app.tools.ranker.dual_recall_and_rerank", return_value=results), \
             patch("app.agents.workflows.recommend_workflow.VideoTools.get_video_info_batch", return_value=infos), \
             patch("app.agents.workflows.recommend_workflow.invoke_with_governor", side_effect=lambda *a, **k: a[3]()), \
             patch("app.tools.memory_tools.MemoryTools.recall_memories", return_value=[]), \
             patch("app.tools.memory_tools.MemoryTools.get_negative_feedback_video_ids", return_value=["v_bad"]):
            result = search_node(_state(top_k=3, user_id="u1", user_profile={"favorite_tags": ["AI"]}))
        vids = [v["video_id"] for v in result["candidate_videos"]]
        assert vids == ["v_ok"]
        assert "v_bad" not in vids


class TestReasonNode:
    def test_builds_reasons_from_tags(self):
        state = _state(candidate_videos=[{"video_id": "v1", "title": "t", "tags": "AI,算法", "author": "老王"}], top_k=3)
        result = reason_node(state)
        assert result["recommended_videos"] == state["candidate_videos"]
        assert any("AI" in r and "算法" in r for r in result["reasons"])

    def test_fallback_reason_uses_title(self):
        state = _state(candidate_videos=[{"video_id": "v1", "title": "值得一看"}], top_k=3)
        result = reason_node(state)
        assert "《值得一看》" in result["reasons"][0]

    def test_reason_uses_profile_behavior(self):
        state = _state(
            candidate_videos=[{"video_id": "v1", "title": "t", "tags": "AI,算法", "author": "老王"}],
            user_profile={"favorite_tags": ["AI"], "favorite_regions": [], "liked_video_ids": ["v1"]},
            top_k=3,
        )
        result = reason_node(state)
        assert "你常看「AI」" in result["reasons"][0]
        assert "你点过同类" in result["reasons"][0]


class TestSummaryNode:
    def test_no_recommendation_message(self):
        state = _state(recommended_videos=[], reasons=[])
        result = summary_node(state)
        assert "推荐" in result["summary"]
        assert result["answer"] == result["summary"]

    def test_builds_markdown_summary(self):
        state = _state(
            recommended_videos=[{"video_id": "v1", "title": "视频甲"}],
            reasons=["理由"],
        )
        result = summary_node(state)
        assert "视频甲" in result["summary"]


class TestSupervisorNode:
    def test_aggregates(self):
        with patch("app.agents.supervisor.Supervisor.aggregate", return_value="最终答案"):
            result = supervisor_node(_state(summary="原始"))
        assert result["answer"] == "最终答案"


class TestColdStartNode:
    def test_question_recall_path(self):
        from app.models import VideoInfo
        results = [{"video_id": "v1", "video_name": "冷启视频", "content": "介绍"}]
        info = VideoInfo(videoId="v1", videoName="冷启视频", videoCover="cover/y.jpg", nickName="作者")
        with patch("app.tools.ranker.dual_recall_and_rerank", return_value=results), \
             patch("app.agents.workflows.recommend_workflow.VideoTools.get_video_info_batch", return_value=[info]), \
             patch("app.agents.workflows.recommend_workflow.invoke_with_governor", side_effect=lambda *a, **k: a[3]()):
            result = cold_start_node(_state(question="推荐"))
        assert result["recommended_videos"][0]["video_id"] == "v1"
        assert "冷启视频" in result["summary"]

    def test_no_question_falls_back_to_recent(self):
        from app.models import VideoInfo
        recent = [VideoInfo(videoId="r1", videoName="最近视频", tags="科技", nickName="UP", playCount=5)]
        with patch("app.agents.workflows.recommend_workflow.VideoTools.get_recent_videos", return_value=recent):
            result = cold_start_node(_state(question=""))
        assert result["recommended_videos"][0]["video_id"] == "r1"


class TestResumeRecommendWorkflow:
    def test_no_checkpoint(self):
        with patch("app.harness.checkpoint.CheckpointManager.get_last_completed", return_value=None):
            result = resume_recommend_workflow("s1")
        assert result["error"] == "无可用 checkpoint"

    def test_already_completed_at_supervisor(self):
        cp = MagicMock()
        cp.step_name = "supervisor_node"
        cp.state_snapshot = {"answer": "已答", "recommended_videos": [], "reasons": []}
        with patch("app.harness.checkpoint.CheckpointManager.get_last_completed", return_value=cp):
            result = resume_recommend_workflow("s1")
        assert result["answer"] == "已答"
        assert result["resumed_from"] == "supervisor_node"

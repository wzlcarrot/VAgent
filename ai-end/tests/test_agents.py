import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock
from app.agents.router import Router
from app.agents.supervisor import Supervisor
from app.models import VideoInfo, VideoPlayHistory


class TestRouter:
    def setup_method(self):
        self.router = Router()

    def test_route_video_question(self):
        result = self.router.route("这个视频讲了什么", {"video_id": "123"})
        assert result == "video_qa_workflow"

    def test_route_video_question_without_context(self):
        result = self.router.route("这个视频讲了什么")
        assert result == "chat_workflow"

    def test_route_recommend_question(self):
        result = self.router.route("给我推荐一个视频")
        assert result == "recommend_workflow"

    def test_route_chat_question(self):
        result = self.router.route("怎么上传视频")
        assert result == "chat_workflow"

    def test_route_default(self):
        result = self.router.route("你好")
        assert result == "chat_workflow"

    def test_route_candidates_video_qa(self):
        candidates = self.router.route_candidates("这个视频讲了什么", {"video_id": "123"})
        assert len(candidates) >= 1
        assert candidates[0][0] == "video_qa_workflow"
        assert candidates[0][1] == 1.0

    def test_route_candidates_user_data(self):
        candidates = self.router.route_candidates("我的收藏有哪些")
        types = [wf for wf, _ in candidates]
        assert "user_data_workflow" in types

    def test_route_candidates_chat_always_included(self):
        candidates = self.router.route_candidates("随便问问")
        types = [wf for wf, _ in candidates]
        assert "chat_workflow" in types

    def test_route_candidates_no_duplicates(self):
        candidates = self.router.route_candidates("推荐我的收藏")
        types = [wf for wf, _ in candidates]
        assert len(types) == len(set(types))


class TestSupervisor:
    def setup_method(self):
        self.supervisor = Supervisor()

    def test_aggregate_video_qa_with_summary(self):
        outputs = {
            "video_info": {"title": "Python教程", "author": "张三"},
            "knowledge": [{"content": "Python基础知识"}],
            "summary": "这是一个Python入门教程"
        }
        result = self.supervisor.aggregate(outputs, "video_qa_workflow")
        assert result == "这是一个Python入门教程"

    def test_aggregate_video_qa_without_summary(self):
        outputs = {
            "video_info": {"title": "Java教程", "author": "李四", "duration": 20},
            "knowledge": [{"content": "Java基础知识"}],
            "summary": ""
        }
        result = self.supervisor.aggregate(outputs, "video_qa_workflow")
        assert "Java教程" in result
        assert "李四" in result

    def test_aggregate_recommend(self):
        outputs = {
            "user_profile": {},
            "recommended_videos": [{"videoName": "测试视频"}],
            "reasons": ["因为你喜欢这类内容"]
        }
        result = self.supervisor.aggregate(outputs, "recommend_workflow")
        assert "测试视频" in result
        assert "因为你喜欢这类内容" in result
        # 空视频列表应返回 fallback
        result_empty = self.supervisor.aggregate(
            {"user_profile": {}, "recommended_videos": [], "reasons": []},
            "recommend_workflow"
        )
        assert "抱歉" in result_empty
        assert "测试视频" in result

    def test_aggregate_chat_with_response(self):
        outputs = {
            "faq_content": ["FAQ1", "FAQ2"],
            "guide_content": ["Guide1"],
            "response": "这是回答"
        }
        result = self.supervisor.aggregate(outputs, "chat_workflow")
        assert result == "这是回答"

    def test_aggregate_chat_without_response(self):
        outputs = {
            "faq_content": ["如何注册？", "如何上传视频？"],
            "guide_content": [],
            "response": ""
        }
        result = self.supervisor.aggregate(outputs, "chat_workflow")
        assert "常见问题" in result
        assert "如何注册" in result

    def test_aggregate_default(self):
        outputs = {"result": "默认结果"}
        result = self.supervisor.aggregate(outputs, "unknown")
        assert result == "默认结果"

    def test_aggregate_empty(self):
        outputs = {}
        result = self.supervisor.aggregate(outputs, "unknown")
        assert "抱歉" in result

    def test_arbitrate_high_priority_wins(self):
        results = [
            ("chat_workflow", "闲聊回答", 0.5),
            ("video_qa_workflow", "视频回答", 0.9),
        ]
        wf, answer, conf = self.supervisor.arbitrate(results)
        assert wf == "video_qa_workflow"
        assert answer == "视频回答"

    def test_arbitrate_fallback_on_empty(self):
        results = [
            ("video_qa_workflow", "", 0.0),
            ("user_data_workflow", "", 0.0),
            ("chat_workflow", "默认回答", 0.5),
        ]
        wf, answer, conf = self.supervisor.arbitrate(results)
        assert answer == "默认回答"

    def test_arbitrate_all_empty(self):
        results = [
            ("video_qa_workflow", "", 0.0),
            ("chat_workflow", "", 0.0),
        ]
        wf, answer, conf = self.supervisor.arbitrate(results)
        assert "抱歉" in answer

    def test_arbitrate_no_results(self):
        wf, answer, conf = self.supervisor.arbitrate([])
        assert "抱歉" in answer
        assert wf == "chat_workflow"

    def test_arbitrate_error_is_invalid(self):
        results = [
            ("video_qa_workflow", "出现error了", 0.8),
            ("chat_workflow", "正常回答", 0.5),
        ]
        wf, answer, conf = self.supervisor.arbitrate(results)
        assert answer == "正常回答"


class TestVideoQAWorkflow:
    @patch("app.agents.workflows.video_qa_workflow.VideoTools.get_video_info")
    @patch("app.agents.workflows.video_qa_workflow.RAGTools.retrieve_knowledge")
    def test_video_info_node_with_video(self, mock_rag, mock_video):
        from app.agents.workflows.video_qa_workflow import video_info_node, knowledge_node, VideoQAState

        mock_video.return_value = VideoInfo(
            videoId="123", videoName="Python教程",
            nickName="张三", duration=30, tags="python,编程"
        )

        state: VideoQAState = {
            "question": "这个视频讲了什么",
            "video_id": "123",
            "user_id": "",
            "session_id": "",
            "video_info": {},
            "knowledge": [],
            "summary": "",
            "answer": "",
            "workflow_type": "video_qa_workflow"
        }

        result = video_info_node(state)
        assert result["video_info"]["title"] == "Python教程"
        assert result["video_info"]["author"] == "张三"

        mock_rag.return_value = [{"content": "Python入门知识", "video_id": "123"}]
        state.update(result)
        result2 = knowledge_node(state)
        assert len(result2["knowledge"]) == 1

    @patch("app.agents.workflows.video_qa_workflow.VideoTools.get_video_info")
    def test_video_info_node_without_video(self, mock_video):
        from app.agents.workflows.video_qa_workflow import video_info_node, VideoQAState

        mock_video.return_value = None

        state: VideoQAState = {
            "question": "你好",
            "video_id": "",
            "user_id": "",
            "session_id": "",
            "video_info": {},
            "knowledge": [],
            "summary": "",
            "answer": "",
            "workflow_type": "video_qa_workflow"
        }

        result = video_info_node(state)
        assert result["video_info"] == {}

    def test_summary_node(self):
        from app.agents.workflows.video_qa_workflow import summary_node, VideoQAState

        state: VideoQAState = {
            "question": "这个视频讲了什么",
            "video_id": "123",
            "user_id": "",
            "session_id": "",
            "video_info": {"title": "Python教程", "author": "张三", "duration": 30},
            "knowledge": [{"content": "Python基础知识"}],
            "summary": "",
            "answer": "",
            "workflow_type": "video_qa_workflow"
        }

        result = summary_node(state)
        assert "Python教程" in result["summary"]
        assert "Python基础知识" in result["summary"]

    def test_router_need_knowledge(self):
        from app.agents.workflows.video_qa_workflow import router_need_knowledge, VideoQAState

        state_with_info: VideoQAState = {
            "question": "", "video_id": "", "user_id": "", "session_id": "",
            "video_info": {"title": "Python教程"}, "knowledge": [],
            "summary": "", "answer": "", "workflow_type": "video_qa_workflow"
        }
        assert router_need_knowledge(state_with_info) == "knowledge_node"

        state_without: VideoQAState = {
            "question": "", "video_id": "", "user_id": "", "session_id": "",
            "video_info": {}, "knowledge": [],
            "summary": "", "answer": "", "workflow_type": "video_qa_workflow"
        }
        assert router_need_knowledge(state_without) == "summary_node"

    @patch("app.agents.workflows.video_qa_workflow.VideoTools.get_video_info")
    @patch("app.agents.workflows.video_qa_workflow.RAGTools.retrieve_knowledge")
    def test_video_qa_graph_invoke(self, mock_rag, mock_video):
        from app.agents.workflows.video_qa_workflow import video_qa_graph, VideoQAState

        mock_video.return_value = VideoInfo(
            videoId="123", videoName="Python教程",
            nickName="张三", duration=30, tags="python,编程"
        )
        mock_rag.return_value = [{"content": "Python入门知识", "video_id": "123"}]

        state: VideoQAState = {
            "question": "这个视频讲了什么",
            "video_id": "123",
            "user_id": "",
            "session_id": "",
            "video_info": {},
            "knowledge": [],
            "summary": "",
            "answer": "",
            "workflow_type": "video_qa_workflow"
        }

        result = video_qa_graph.invoke(state)
        assert len(result.get("answer", "")) > 0


class TestRecommendWorkflow:
    @patch("app.agents.workflows.recommend_workflow.UserTools.get_play_history")
    @patch("app.agents.workflows.recommend_workflow.UserTools.get_favorites")
    @patch("app.agents.workflows.recommend_workflow.UserTools.get_liked_videos")
    def test_profile_node_with_history(self, mock_liked, mock_fav, mock_history):
        from app.agents.workflows.recommend_workflow import profile_node, RecommendState

        mock_history.return_value = [
            VideoPlayHistory(videoId="v1", videoName="Python入门"),
            VideoPlayHistory(videoId="v2", videoName="Java基础")
        ]
        mock_fav.return_value = []
        mock_liked.return_value = []

        state: RecommendState = {
            "user_id": "u1", "question": "", "session_id": "",
            "user_profile": {}, "candidate_videos": [],
            "recommended_videos": [], "reasons": [],
            "summary": "", "answer": "", "workflow_type": "recommend_workflow"
        }

        result = profile_node(state)
        profile = result["user_profile"]
        assert profile["play_count"] == 2
        assert "Python入门" in profile["favorite_tags"] or "Java基础" in profile["favorite_tags"]

    @patch("app.agents.workflows.recommend_workflow.UserTools.get_play_history")
    @patch("app.agents.workflows.recommend_workflow.UserTools.get_favorites")
    @patch("app.agents.workflows.recommend_workflow.UserTools.get_liked_videos")
    def test_profile_node_without_history(self, mock_liked, mock_fav, mock_history):
        from app.agents.workflows.recommend_workflow import profile_node, RecommendState

        mock_history.return_value = []
        mock_fav.return_value = []
        mock_liked.return_value = []

        state: RecommendState = {
            "user_id": "u1", "question": "", "session_id": "",
            "user_profile": {}, "candidate_videos": [],
            "recommended_videos": [], "reasons": [],
            "summary": "", "answer": "", "workflow_type": "recommend_workflow"
        }

        result = profile_node(state)
        assert result["user_profile"]["play_count"] == 0

    def test_cold_start_node(self):
        from app.agents.workflows.recommend_workflow import cold_start_node, RecommendState
        from app.tools import VideoTools

        mock_videos = [
            VideoInfo(videoId="v1", videoName="热门视频1", nickName="作者1"),
            VideoInfo(videoId="v2", videoName="热门视频2", nickName="作者2"),
        ]

        with patch.object(VideoTools, "get_recent_videos", return_value=mock_videos, create=True):
            state: RecommendState = {
                "user_id": "u1", "question": "", "session_id": "",
                "user_profile": {}, "candidate_videos": [],
                "recommended_videos": [], "reasons": [],
                "summary": "", "answer": "", "workflow_type": "recommend_workflow"
            }

            result = cold_start_node(state)
            assert len(result["recommended_videos"]) == 2
            assert "热门视频1" in result["summary"]

    def test_reason_node(self):
        from app.agents.workflows.recommend_workflow import reason_node, RecommendState

        state: RecommendState = {
            "user_id": "u1", "question": "", "session_id": "",
            "user_profile": {"favorite_tags": ["Python"], "watched_video_ids": ["v_old"]},
            "candidate_videos": [{"video_id": "v1", "title": "Python进阶"}],
            "recommended_videos": [], "reasons": [],
            "summary": "", "answer": "", "workflow_type": "recommend_workflow"
        }

        result = reason_node(state)
        assert len(result["reasons"]) == 1
        assert "Python" in result["reasons"][0]

    @patch("app.agents.workflows.recommend_workflow.UserTools.get_play_history")
    @patch("app.agents.workflows.recommend_workflow.UserTools.get_favorites")
    @patch("app.agents.workflows.recommend_workflow.UserTools.get_liked_videos")
    def test_has_history_router(self, mock_liked, mock_fav, mock_history):
        from app.agents.workflows.recommend_workflow import has_history_router, profile_node, RecommendState

        mock_history.return_value = [VideoPlayHistory(videoId="v1", videoName="Python入门")]
        mock_fav.return_value = []
        mock_liked.return_value = []

        state: RecommendState = {
            "user_id": "u1", "question": "", "session_id": "",
            "user_profile": {}, "candidate_videos": [],
            "recommended_videos": [], "reasons": [],
            "summary": "", "answer": "", "workflow_type": "recommend_workflow"
        }

        state.update(profile_node(state))
        assert has_history_router(state) == "search_node"

        mock_history.return_value = []
        state2: RecommendState = {
            "user_id": "u1", "question": "", "session_id": "",
            "user_profile": {}, "candidate_videos": [],
            "recommended_videos": [], "reasons": [],
            "summary": "", "answer": "", "workflow_type": "recommend_workflow"
        }
        state2.update(profile_node(state2))
        assert has_history_router(state2) == "summary_node"


class TestChatGraph:
    @patch("app.agents.workflows.chat_graph.RAGTools.retrieve_knowledge")
    def test_faq_node(self, mock_rag):
        from app.agents.workflows.chat_graph import _faq_node, ChatState

        mock_rag.return_value = [{"content": "如何注册账号？"}]

        state: ChatState = {
            "question": "怎么注册",
            "conversation_history": [],
            "faq_results": [], "guide_results": [],
            "response": "", "answer": "",
            "full_response": "", "workflow_type": "chat_workflow"
        }

        result = _faq_node(state)
        assert len(result["faq_results"]) == 1

    @patch("app.agents.workflows.chat_graph.RAGTools.retrieve_knowledge")
    def test_guide_node(self, mock_rag):
        from app.agents.workflows.chat_graph import _guide_node, ChatState

        mock_rag.return_value = [{"content": "点击上传按钮"}]

        state: ChatState = {
            "question": "怎么上传",
            "conversation_history": [],
            "faq_results": [], "guide_results": [],
            "response": "", "answer": "",
            "full_response": "", "workflow_type": "chat_workflow"
        }

        result = _guide_node(state)
        assert len(result["guide_results"]) == 1

    def test_has_knowledge_router(self):
        from app.agents.workflows.chat_graph import _has_knowledge_router, ChatState

        state_with_faq: ChatState = {
            "question": "", "conversation_history": [],
            "faq_results": [{"content": "FAQ"}], "guide_results": [],
            "response": "", "answer": "",
            "full_response": "", "workflow_type": "chat_workflow"
        }
        assert _has_knowledge_router(state_with_faq) == "llm_node"

        state_with_guide: ChatState = {
            "question": "", "conversation_history": [],
            "faq_results": [], "guide_results": [{"content": "Guide"}],
            "response": "", "answer": "",
            "full_response": "", "workflow_type": "chat_workflow"
        }
        assert _has_knowledge_router(state_with_guide) == "llm_node"

        state_empty: ChatState = {
            "question": "", "conversation_history": [],
            "faq_results": [], "guide_results": [],
            "response": "", "answer": "",
            "full_response": "", "workflow_type": "chat_workflow"
        }
        assert _has_knowledge_router(state_empty) == "supervisor_node"

    @patch("app.agents.workflows.chat_graph.RAGTools.retrieve_knowledge")
    @patch("app.agents.workflows.chat_graph.LLM_tools.stream_chat")
    def test_chat_graph_invoke(self, mock_llm, mock_rag):
        from app.agents.workflows.chat_graph import run_chat_workflow

        mock_rag.return_value = [{"content": "如何注册账号？"}]

        async def _mock_stream(*args, **kwargs):
            for token in ["这是", "注册", "流程"]:
                yield token
        mock_llm.return_value = _mock_stream()

        result = run_chat_workflow("怎么注册", [])
        assert len(result.get("answer", "")) > 0


class TestRouterUserData:
    def setup_method(self):
        self.router = Router()

    def test_route_user_data_my_favorites(self):
        result = self.router.route("我的收藏有哪些")
        assert result == "user_data_workflow"

    def test_route_user_data_today_like(self):
        result = self.router.route("我今天点了多少赞")
        assert result == "user_data_workflow"

    def test_route_user_data_history(self):
        result = self.router.route("我的播放历史")
        assert result == "user_data_workflow"

    def test_route_user_data_top_liked(self):
        result = self.router.route("我点赞最多的视频")
        assert result == "user_data_workflow"

    def test_route_user_data_not_recommend_conflict(self):
        result = self.router.route("推荐我的收藏")
        assert result == "user_data_workflow"

    def test_route_video_without_context(self):
        result = self.router.route("这个视频讲解")
        assert result == "chat_workflow"

    def test_route_normal_chat_not_trigger(self):
        result = self.router.route("你好")
        assert result == "chat_workflow"


class TestSupervisorUserData:
    def setup_method(self):
        self.supervisor = Supervisor()

    def test_aggregate_user_data_with_response(self):
        outputs = {
            "response": "你今天共点赞了5次",
            "query_result": {"count": 5, "summary_text": "你今天共点赞了5次"},
            "intent": {"data_type": "like", "time_range": "today", "aggregation": "count"}
        }
        result = self.supervisor.aggregate(outputs, "user_data_workflow")
        assert result == "你今天共点赞了5次"

    def test_aggregate_user_data_without_response(self):
        outputs = {
            "response": "",
            "query_result": {"count": 3, "summary_text": "你共收藏了3个视频"},
            "intent": {}
        }
        result = self.supervisor.aggregate(outputs, "user_data_workflow")
        assert "收藏" in result

    def test_aggregate_user_data_empty(self):
        outputs = {"response": "", "query_result": {}, "intent": {}}
        result = self.supervisor.aggregate(outputs, "user_data_workflow")
        assert "抱歉" in result


class TestUserDataWorkflow:
    def test_intent_node_keyword_like_count_today(self):
        from app.agents.workflows.user_data_workflow import intent_node, UserDataState

        state: UserDataState = {
            "question": "我今天点了多少赞",
            "user_id": "u1", "session_id": "",
            "intent": {}, "query_result": {},
            "response": "", "answer": "", "workflow_type": "user_data_workflow"
        }

        result = intent_node(state)
        intent = result["intent"]
        assert intent["data_type"] == "like"
        assert intent["time_range"] == "today"
        assert intent["aggregation"] == "count"

    def test_intent_node_keyword_favorite_list(self):
        from app.agents.workflows.user_data_workflow import intent_node, UserDataState

        state: UserDataState = {
            "question": "我的收藏有哪些",
            "user_id": "u1", "session_id": "",
            "intent": {}, "query_result": {},
            "response": "", "answer": "", "workflow_type": "user_data_workflow"
        }

        result = intent_node(state)
        intent = result["intent"]
        assert intent["data_type"] == "favorite"
        assert intent["aggregation"] == "list"

    def test_intent_node_keyword_history(self):
        from app.agents.workflows.user_data_workflow import intent_node, UserDataState

        state: UserDataState = {
            "question": "我的播放历史",
            "user_id": "u1", "session_id": "",
            "intent": {}, "query_result": {},
            "response": "", "answer": "", "workflow_type": "user_data_workflow"
        }

        result = intent_node(state)
        intent = result["intent"]
        assert intent["data_type"] == "history"
        assert intent["aggregation"] == "list"

    def test_intent_node_keyword_top_liked(self):
        from app.agents.workflows.user_data_workflow import intent_node, UserDataState

        state: UserDataState = {
            "question": "我点赞最多的视频",
            "user_id": "u1", "session_id": "",
            "intent": {}, "query_result": {},
            "response": "", "answer": "", "workflow_type": "user_data_workflow"
        }

        result = intent_node(state)
        intent = result["intent"]
        assert intent["data_type"] == "like"
        assert intent["aggregation"] == "top"

    @patch("app.agents.workflows.user_data_workflow.UserTools.get_today_like_count")
    def test_query_node_today_like(self, mock_count):
        from app.agents.workflows.user_data_workflow import query_node, UserDataState

        mock_count.return_value = 5

        state: UserDataState = {
            "question": "我今天点了多少赞",
            "user_id": "u1", "session_id": "",
            "intent": {"data_type": "like", "time_range": "today", "aggregation": "count"},
            "query_result": {},
            "response": "", "answer": "", "workflow_type": "user_data_workflow"
        }

        result = query_node(state)
        assert result["query_result"]["count"] == 5
        assert "5" in result["query_result"]["summary_text"]

    @patch("app.agents.workflows.user_data_workflow.UserTools.get_recent_favorites")
    def test_query_node_favorite_list(self, mock_fav):
        from app.agents.workflows.user_data_workflow import query_node, UserDataState

        mock_fav.return_value = {
            "videos": [{"video_id": "v1", "video_name": "测试视频"}],
            "total": 15
        }

        state: UserDataState = {
            "question": "我的收藏有哪些",
            "user_id": "u1", "session_id": "",
            "intent": {"data_type": "favorite", "time_range": "all", "aggregation": "list"},
            "query_result": {},
            "response": "", "answer": "", "workflow_type": "user_data_workflow"
        }

        result = query_node(state)
        assert result["query_result"]["total"] == 15
        assert "测试视频" in result["query_result"]["summary_text"]

    @patch("app.agents.workflows.user_data_workflow.UserTools.get_top_liked_videos")
    def test_query_node_top_liked(self, mock_top):
        from app.agents.workflows.user_data_workflow import query_node, UserDataState

        mock_top.return_value = [
            {"video_id": "v1", "video_name": "Python教程", "count": 10}
        ]

        state: UserDataState = {
            "question": "我点赞最多的视频",
            "user_id": "u1", "session_id": "",
            "intent": {"data_type": "like", "time_range": "all", "aggregation": "top"},
            "query_result": {},
            "response": "", "answer": "", "workflow_type": "user_data_workflow"
        }

        result = query_node(state)
        assert "Python教程" in result["query_result"]["summary_text"]
        assert "10" in result["query_result"]["summary_text"]

    def test_query_node_no_user_id(self):
        from app.agents.workflows.user_data_workflow import query_node, UserDataState

        state: UserDataState = {
            "question": "我的数据",
            "user_id": "", "session_id": "",
            "intent": {"data_type": "like", "time_range": "all", "aggregation": "count"},
            "query_result": {},
            "response": "", "answer": "", "workflow_type": "user_data_workflow"
        }

        result = query_node(state)
        assert "error" in result["query_result"]

    def test_query_node_unknown_intent(self):
        from app.agents.workflows.user_data_workflow import query_node, UserDataState

        state: UserDataState = {
            "question": "不知道",
            "user_id": "u1", "session_id": "",
            "intent": {"data_type": "unknown", "time_range": "all", "aggregation": "unknown"},
            "query_result": {},
            "response": "", "answer": "", "workflow_type": "user_data_workflow"
        }

        result = query_node(state)
        assert "error" in result["query_result"]

    @patch("app.agents.workflows.user_data_workflow.UserTools.get_recent_history")
    def test_query_node_history(self, mock_history):
        from app.agents.workflows.user_data_workflow import query_node, UserDataState

        mock_history.return_value = {
            "videos": [{"video_id": "v1", "video_name": "看过视频"}],
            "total": 8
        }

        state: UserDataState = {
            "question": "我的播放历史",
            "user_id": "u1", "session_id": "",
            "intent": {"data_type": "history", "time_range": "all", "aggregation": "list"},
            "query_result": {},
            "response": "", "answer": "", "workflow_type": "user_data_workflow"
        }

        result = query_node(state)
        assert result["query_result"]["total"] == 8
        assert "看过视频" in result["query_result"]["summary_text"]

    @patch("app.agents.workflows.user_data_workflow.LLM_tools.chat")
    @patch("app.agents.workflows.user_data_workflow.UserTools.get_total_like_count")
    def test_user_data_graph_invoke(self, mock_count, mock_llm):
        from app.agents.workflows.user_data_workflow import user_data_graph, UserDataState

        mock_count.return_value = 42
        mock_llm.side_effect = lambda *a, **kw: "你共点赞了42次"

        state: UserDataState = {
            "question": "我总共点了多少赞",
            "user_id": "u1", "session_id": "",
            "intent": {}, "query_result": {},
            "response": "", "answer": "", "workflow_type": "user_data_workflow"
        }

        result = user_data_graph.invoke(state)
        assert len(result.get("answer", "")) > 0

    @patch("app.agents.workflows.user_data_workflow.LLM_tools.chat")
    @patch("app.agents.workflows.user_data_workflow.UserTools.get_total_like_count")
    def test_run_user_data_workflow(self, mock_count, mock_llm):
        from app.agents.workflows.user_data_workflow import run_user_data_workflow

        mock_count.return_value = 42
        mock_llm.side_effect = lambda *a, **kw: "你共点赞了42次"

        result = run_user_data_workflow("我总共点了多少赞", user_id="u1")
        assert "42" in result.get("answer", "")
        assert result["workflow_type"] == "user_data_workflow"

    @patch("app.agents.workflows.chat_graph.LLM_tools.chat_sync")
    def test_run_chat_workflow_fallback(self, mock_llm):
        from app.agents.workflows.chat_graph import run_chat_workflow
        mock_llm.return_value = ""
        result = run_chat_workflow("你好")
        assert result["workflow_type"] == "chat_workflow"

    def test_supervisor_detects_fallback_response(self):
        from app.tools.output_guard import FALLBACK_RESPONSE
        supervisor = Supervisor()
        results = [("chat_workflow", FALLBACK_RESPONSE, 0.0)]
        wf, answer, conf = supervisor.arbitrate(results)
        assert answer == FALLBACK_RESPONSE

    def test_router_no_keyword_no_semantic_falls_to_llm(self):
        router = Router()
        router._load_exemplar_embeddings = MagicMock()
        router._exemplar_embeddings = {}
        result = router.route("一个完全随机的奇怪问题xxxxyyyy", {})
        assert result in ("chat_workflow", "")


class TestToolSandbox:
    """工具沙箱校验：deny by default + 白名单 + public 显式放行"""

    def setup_method(self):
        from app.tools.tool_registry import ToolRegistry, Tool
        self.registry = ToolRegistry()
        self._saved = dict(self.registry._tools)
        self.registry._tools.clear()
        self.tool_restricted = Tool(
            name="tool_restricted",
            description="restricted",
            parameters={},
            allowed_agents=["video_qa_workflow"],
        )
        self.tool_public = Tool(
            name="tool_public",
            description="public",
            parameters={},
            public=True,
        )
        self.tool_empty = Tool(
            name="tool_empty",
            description="no whitelist, no public",
            parameters={},
            allowed_agents=[],
        )
        self.registry.register(self.tool_restricted)
        self.registry.register(self.tool_public)
        self.registry.register(self.tool_empty)

    def teardown_method(self):
        from app.tools.tool_registry import ToolRegistry
        reg = ToolRegistry()
        reg._tools.clear()
        reg._tools.update(self._saved)

    def test_nonexistent_tool_denied(self):
        from app.tools.tool_registry import ToolSandbox
        assert ToolSandbox.validate_call("does_not_exist", "video_qa_workflow") is False

    def test_restricted_tool_allowed_for_listed_agent(self):
        from app.tools.tool_registry import ToolSandbox
        assert ToolSandbox.validate_call("tool_restricted", "video_qa_workflow") is True

    def test_restricted_tool_denied_for_other_agent(self):
        from app.tools.tool_registry import ToolSandbox
        assert ToolSandbox.validate_call("tool_restricted", "chat_workflow") is False

    def test_public_tool_allowed_for_any_agent(self):
        from app.tools.tool_registry import ToolSandbox
        assert ToolSandbox.validate_call("tool_public", "any_agent_at_all") is True

    def test_empty_whitelist_denied_by_default(self):
        """核心 bug 修复：没有 allowed_agents 也没有 public 标记的工具必须拒绝"""
        from app.tools.tool_registry import ToolSandbox
        assert ToolSandbox.validate_call("tool_empty", "video_qa_workflow") is False
        assert ToolSandbox.validate_call("tool_empty", "router") is False


class TestToolGovernorSandboxIntegration:
    """ToolGovernor.gate() 必须执行沙箱校验，拒绝时不消耗 rate limit 配额"""

    def test_gate_rejects_sandbox_violation(self):
        from app.harness.tool_governor import ToolGovernor, ToolAccessDenied
        from app.tools.tool_registry import ToolRegistry, Tool, ToolSandbox

        reg = ToolRegistry()
        saved = dict(reg._tools)
        reg._tools.clear()
        reg.register(Tool(
            name="qa_only_tool",
            description="",
            parameters={},
            allowed_agents=["video_qa_workflow"],
        ))

        try:
            gov = ToolGovernor()
            gov.reset_session("sandbox_test_session")

            with __import__("pytest").raises(ToolAccessDenied):
                gov.gate(
                    session_id="sandbox_test_session",
                    agent="user_data_workflow",
                    tool_name="qa_only_tool",
                    arguments={},
                    execute_fn=lambda: "should not run",
                    record_artifact=False,
                )
            # 关键断言：拒绝后该 session 的计数没有增加
            assert gov.get_call_count("sandbox_test_session", "qa_only_tool") == 0
        finally:
            reg._tools.clear()
            reg._tools.update(saved)

    def test_gate_allows_listed_agent(self):
        from app.harness.tool_governor import ToolGovernor
        from app.tools.tool_registry import ToolRegistry, Tool

        reg = ToolRegistry()
        saved = dict(reg._tools)
        reg._tools.clear()
        reg.register(Tool(
            name="qa_only_tool_2",
            description="",
            parameters={},
            allowed_agents=["video_qa_workflow"],
        ))

        try:
            gov = ToolGovernor()
            gov.reset_session("sandbox_test_session_2")
            result = gov.gate(
                session_id="sandbox_test_session_2",
                agent="video_qa_workflow",
                tool_name="qa_only_tool_2",
                arguments={},
                execute_fn=lambda: "ok",
                record_artifact=False,
            )
            assert result == "ok"
            assert gov.get_call_count("sandbox_test_session_2", "qa_only_tool_2") == 1
        finally:
            reg._tools.clear()
            reg._tools.update(saved)


class TestLLMRaceConditionFix:
    """验证 chat_with_tools_router 不再修改全局 settings.llm_provider"""

    def test_router_does_not_mutate_global_settings(self):
        """核心 bug 修复：调用 chat_with_tools_router 后全局 settings.llm_provider 保持不变"""
        from app.config import settings
        from app.tools.llm_tools import LLM_tools
        from unittest.mock import patch, MagicMock

        original_provider = settings.llm_provider
        original_router_provider = settings.router_llm_provider
        try:
            settings.router_llm_provider = "minimax"
            settings.llm_provider = "deepseek"

            with patch.object(LLM_tools, "chat_with_tools", return_value={"content": "ok"}) as mock:
                # 调用 router 专用入口
                LLM_tools.chat_with_tools_router([], [])
                # 关键断言：全局 settings.llm_provider 没有被改
                assert settings.llm_provider == "deepseek", (
                    f"全局 settings.llm_provider 被改成了 {settings.llm_provider}，"
                    f"这会导致多线程下 router 用 minimax 模型，普通用 deepseek 模型的串台"
                )
                # 验证 chat_with_tools 收到的是 provider 参数
                call_kwargs = mock.call_args.kwargs
                assert call_kwargs.get("provider") == "minimax"
        finally:
            settings.llm_provider = original_provider
            settings.router_llm_provider = original_router_provider

    def test_resolve_provider_does_not_touch_settings(self):
        """_resolve_provider 应该是纯函数，只读 settings 不写"""
        from app.config import settings
        from app.tools.llm_tools import _resolve_provider
        original = settings.llm_provider
        try:
            settings.llm_provider = "deepseek"
            base_url, model, api_key = _resolve_provider()
            assert "deepseek" in base_url.lower() or "deepseek" in model.lower()
            assert settings.llm_provider == "deepseek"

            base_url2, model2, api_key2 = _resolve_provider("minimax")
            assert "minimax" in model2.lower() or "minimax" in base_url2.lower()
            # 关键：调用 _resolve_provider 不会修改 settings
            assert settings.llm_provider == "deepseek"
        finally:
            settings.llm_provider = original


class TestRedisCircuitBreaker:
    """验证 Redis 熔断器：失败时熔断、冷却期内不重连、冷却后允许重试"""

    def test_circuit_opens_after_failure(self):
        import app.tools.context_tools as ct
        # 重置熔断器
        ct._redis_circuit_open = False
        ct._last_redis_failure = 0.0
        ct._redis_client = None

        # 模拟 redis 不可用：注入一个 ping 抛异常的客户端
        fake_client = MagicMock()
        fake_client.ping.side_effect = Exception("connection refused")
        with patch("redis.Redis", return_value=fake_client):
            result = ct._get_redis()
            assert result is None
            assert ct._redis_circuit_open is True
            assert ct._last_redis_failure > 0

    def test_circuit_short_circuits_during_cooldown(self):
        """熔断开启 + 冷却期内：不应尝试连接，直接返回 None"""
        import app.tools.context_tools as ct
        import time as _time
        ct._redis_circuit_open = True
        ct._last_redis_failure = _time.time()  # 刚刚失败
        ct._redis_client = None

        # 即便 redis 恢复可用，冷却期内不应尝试连接
        with patch("redis.Redis") as mock_redis:
            result = ct._get_redis()
            assert result is None
            assert mock_redis.call_count == 0, "冷却期内不应调用 redis.Redis()"

    def test_circuit_half_opens_after_cooldown(self):
        """冷却期过后：允许一次重试"""
        import app.tools.context_tools as ct
        import time as _time
        ct._redis_circuit_open = True
        ct._last_redis_failure = _time.time() - 10.0  # 10 秒前失败
        ct._redis_client = None

        # 模拟恢复：ping 成功
        fake_client = MagicMock()
        fake_client.ping.return_value = True
        with patch("redis.Redis", return_value=fake_client):
            result = ct._get_redis()
            assert result is fake_client
            # 成功后熔断器关闭
            assert ct._redis_circuit_open is False
            assert ct._last_redis_failure == 0.0


class TestAuthEnforcement:
    """验证 require_auth 强制登录，无 token 抛 401"""

    def test_require_auth_no_header_raises_401(self):
        from app.routers._shared import require_auth
        from fastapi import HTTPException
        request = MagicMock()
        request.headers.get.return_value = ""  # 没有 Authorization 头
        try:
            require_auth(request)
            assert False, "应该抛 401"
        except HTTPException as e:
            assert e.status_code == 401

    def test_require_auth_invalid_token_raises_401(self):
        from app.routers._shared import require_auth, _token_set
        from fastapi import HTTPException
        import time
        request = MagicMock()
        request.headers.get.return_value = "Bearer invalid_token_xxx"
        try:
            require_auth(request)
            assert False, "应该抛 401"
        except HTTPException as e:
            assert e.status_code == 401

    def test_require_auth_valid_token_returns_user_id(self):
        from app.routers._shared import require_auth, _token_set
        import time
        token = "test_valid_token_abc"
        _token_set(token, "user_999", time.time() + 3600)
        request = MagicMock()
        request.headers.get.return_value = f"Bearer {token}"
        result = require_auth(request)
        assert result == "user_999"

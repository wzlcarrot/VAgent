import pytest
from unittest.mock import patch, MagicMock
from app.agents.router import Router
from app.agents.supervisor import Supervisor



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

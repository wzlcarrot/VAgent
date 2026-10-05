"""智能追问澄清器测试。"""
from app.agents.workflows.constants import WorkflowType
from app.conversation.intent_clarifier import IntentClarifier, has_category_keyword, has_similar_intent


class TestHasCategoryKeyword:
    def test_plain_keyword_hit(self):
        assert has_category_keyword("推荐科技类的视频") is True
        assert has_category_keyword("来点美食") is True
        assert has_category_keyword("想看 AI 内容") is True

    def test_no_keyword(self):
        assert has_category_keyword("推荐一些视频") is False
        assert has_category_keyword("有什么推荐的") is False
        assert has_category_keyword("推荐两个类似的") is False
        assert has_category_keyword("") is False
        assert has_category_keyword(None) is False

    def test_not_fooled_by_other_words(self):
        assert has_category_keyword("今天天气怎么样") is False
        assert has_category_keyword("平台有什么功能") is False


class TestHasSimilarIntent:
    def test_similar_keywords(self):
        assert has_similar_intent("推荐两个类似的") is True
        assert has_similar_intent("想看差不多的") is True
        assert has_similar_intent("推荐这个的同类") is True

    def test_not_similar(self):
        assert has_similar_intent("推荐一些视频") is False
        assert has_similar_intent("推荐科技类的") is False
        assert has_similar_intent("") is False
        assert has_similar_intent(None) is False


class TestNeedClarification:
    def test_recommend_new_user_no_keyword_asks(self):
        assert IntentClarifier.need_clarification(
            intent=WorkflowType.RECOMMEND, user_preference={}, question="推荐一些视频",
        ) is True

    def test_recommend_new_user_with_category_does_not_ask(self):
        """回归：新用户问题里已写明「科技」时不再追问，直接推荐。"""
        assert IntentClarifier.need_clarification(
            intent=WorkflowType.RECOMMEND, user_preference={}, question="推荐科技类的视频",
        ) is False

    def test_recommend_new_user_with_ai_alias_does_not_ask(self):
        assert IntentClarifier.need_clarification(
            intent=WorkflowType.RECOMMEND, user_preference={}, question="推荐两个 AI 相关的",
        ) is False

    def test_recommend_new_user_similar_does_not_ask(self):
        """回归：新用户说「推荐两个类似的」不再被追问菜单截胡，直接推荐。"""
        assert IntentClarifier.need_clarification(
            intent=WorkflowType.RECOMMEND, user_preference={}, question="推荐两个类似的",
        ) is False

    def test_recommend_similar_to_current_without_id_asks(self):
        """点了「类似当前视频」却没有带入 video_id，不能拿目录/画像冒充。"""
        assert IntentClarifier.need_clarification(
            intent=WorkflowType.RECOMMEND, user_preference={},
            question="推荐和当前视频类似的视频",
        ) is True
        assert IntentClarifier.need_clarification(
            intent=WorkflowType.RECOMMEND,
            user_preference={"liked_video_ids": ["v1"]},
            question="这个视频有没有相似的",
        ) is True
        text = IntentClarifier.get_clarification(
            intent=WorkflowType.RECOMMEND, question="推荐和当前视频类似的视频",
        )
        assert "没有带入当前视频" in text

    def test_recommend_similar_to_current_with_id_does_not_ask(self):
        assert IntentClarifier.need_clarification(
            intent=WorkflowType.RECOMMEND, video_id="demo01",
            user_preference={"liked_video_ids": ["v1"]},
            question="推荐和当前视频类似的视频",
        ) is False

    def test_recommend_new_user_bare_question_still_asks(self):
        """光秃秃「推荐一些视频」仍追问（产品设计：新用户无偏好需要引导）。"""
        assert IntentClarifier.need_clarification(
            intent=WorkflowType.RECOMMEND, user_preference={}, question="推荐一些视频",
        ) is True

    def test_recommend_with_pref_does_not_ask(self):
        assert IntentClarifier.need_clarification(
            intent=WorkflowType.RECOMMEND,
            user_preference={"favorite_tags": ["科技"]},
            question="推荐一些视频",
        ) is False

    def test_recommend_with_play_history_does_not_ask(self):
        assert IntentClarifier.need_clarification(
            intent=WorkflowType.RECOMMEND,
            user_preference={"play_count": 3, "watched_video_ids": ["v1"]},
            question="推荐一些视频",
        ) is False

    def test_recommend_with_likes_does_not_ask(self):
        assert IntentClarifier.need_clarification(
            intent=WorkflowType.RECOMMEND,
            user_preference={"liked_video_ids": ["v1"]},
            question="推荐一些视频",
        ) is False

    def test_video_qa_no_id_asks(self):
        assert IntentClarifier.need_clarification(
            intent=WorkflowType.VIDEO_QA, video_id=None,
        ) is True

    def test_video_qa_with_id_does_not_ask(self):
        assert IntentClarifier.need_clarification(
            intent=WorkflowType.VIDEO_QA, video_id="v1",
        ) is False

    def test_chat_with_keywords_does_not_ask(self):
        assert IntentClarifier.need_clarification(
            intent=WorkflowType.CHAT, mentioned_keywords=["上传", "视频"], question="怎么上传视频",
        ) is False

    def test_chat_vague_greeting_goes_to_chat_not_clarifier(self):
        """空泛招呼走闲聊工作流，澄清器不再截成功能菜单。"""
        assert IntentClarifier.need_clarification(
            intent=WorkflowType.CHAT, mentioned_keywords=[], question="你好",
        ) is False
        assert IntentClarifier.need_clarification(
            intent=WorkflowType.CHAT, mentioned_keywords=[], question="在吗",
        ) is False

    def test_chat_chinese_greeting_not_blocked_by_split_token(self):
        """中文整句 split() 后是一个词，招呼仍不进澄清器。"""
        assert IntentClarifier.need_clarification(
            intent=WorkflowType.CHAT, mentioned_keywords=["你好"], question="你好",
        ) is False
        assert IntentClarifier.need_clarification(
            intent=WorkflowType.CHAT, mentioned_keywords=["在吗"], question="在吗",
        ) is False

    def test_chat_short_question_with_content_not_vague(self):
        """非空泛的短问题（有实质内容）不追问。"""
        assert IntentClarifier.need_clarification(
            intent=WorkflowType.CHAT, mentioned_keywords=[], question="怎么上传视频",
        ) is False
        assert IntentClarifier.need_clarification(
            intent=WorkflowType.CHAT, mentioned_keywords=[], question="什么是ViewHub",
        ) is False

    def test_chat_long_greeting_with_context_not_vague(self):
        """「你好，我想知道怎么上传视频」有实质内容，不追问。"""
        assert IntentClarifier.need_clarification(
            intent=WorkflowType.CHAT, mentioned_keywords=[], question="你好，我想知道怎么上传视频",
        ) is False

    def test_backward_compat_no_question_param(self):
        """question 是新增可选参数，不传时按旧行为（无偏好就追问）。"""
        assert IntentClarifier.need_clarification(
            intent=WorkflowType.RECOMMEND, user_preference={}, mentioned_keywords=[],
        ) is True

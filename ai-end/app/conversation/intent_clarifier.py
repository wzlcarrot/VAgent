"""
智能追问与澄清

解决问题：
  用户：推荐视频
  旧 AI：[随机推荐 5 个视频] ❌ 没个性化
  新 AI：✅ "您喜欢哪类视频呢？科技、娱乐还是学习？"

触发规则（不调 LLM，规则生成）：
1. recommend：新用户（无任何偏好记忆）→ 追问偏好类型
2. video_qa：缺 video_id → 追问视频来源
3. chat：模糊平台问题 + 无具体关键词 → 引导用户描述

设计：
- 纯规则，不消耗 LLM 配额
- 追问话术集中维护（运营可改）
- 返回 "需要追问" 标记，下游 supervisor 决定是否触发
"""
import logging
from typing import Any, Dict, List, Optional

from app.agents.workflows.constants import WorkflowType

logger = logging.getLogger(__name__)


# 偏好分类（运营可调整）
_PREFERENCE_CATEGORIES = [
    ("科技", ["科技", "技术", "编程", "AI", "互联网", "数码"]),
    ("娱乐", ["娱乐", "明星", "综艺", "搞笑", "八卦"]),
    ("学习", ["学习", "教程", "知识", "课程", "考试"]),
    ("生活", ["生活", "美食", "旅行", "vlog", "日常"]),
    ("游戏", ["游戏", "电竞", "攻略", "直播"]),
    ("音乐", ["音乐", "歌曲", "翻唱", "MV", "演奏"]),
    ("体育", ["体育", "篮球", "足球", "健身", "运动"]),
    ("影视", ["影视", "电影", "剧集", "解说", "影评"]),
]


_CLARIFICATIONS = {
    "recommend_new_user": "欢迎！我来给你推荐视频。请问你喜欢哪一类？\n"
                          "{categories}\n"
                          "（直接回复类别名即可，例如「科技」）",

    "recommend_no_history": "我还没看过你的观看记录。{categories}\n"
                            "想看哪类呢？告诉我吧～",

    "video_qa_no_id": "你想了解哪个视频呢？\n"
                      "可以告诉我视频标题、UP 主名字，或者直接粘贴视频链接。",

    "video_qa_ambiguous": "你提到的「{keyword}」我不太确定是哪个视频。能再具体点吗？\n"
                          "比如视频标题里的关键词、UP 主名字，或发布时间。",

    "chat_vague_platform": "想了解 ViewHub 的哪方面功能？\n"
                           "例如：账号注册、视频上传、点赞收藏、弹幕、AI 助手使用等。",
}


def _format_categories(limit: int = 6) -> str:
    """格式化类别列表成菜单"""
    return "、".join(f"【{name}】" for name, _ in _PREFERENCE_CATEGORIES[:limit])


# 相似意图词：问题含这些词说明用户想要"同类/类似"推荐（基于当前观看或上下文），
# 已足够具体，不应追问。如「推荐两个类似的」「像这个的」。
_SIMILAR_INTENT_KEYWORDS = ["类似", "相似", "同款", "差不多", "像这个", "这种", "同类"]

# 空泛招呼词：chat 意图下仅命中这些（无实质功能诉求）才追问引导。
# 中文 `question.split()` 会把整句当一个 token，不能用分词结果判断"有无关键词"，
# 改为：问题本身不含任何功能/疑问实质词时才视为模糊。
_VAGUE_GREETINGS = ["你好", "您好", "在吗", "在么", "hi", "hello", "help", "哈喽", "嗨", "有人吗"]


def has_category_keyword(question: str) -> bool:
    """判断问题里是否已经写明了偏好类别（科技/美食/AI/教程…）。

    用包含匹配而非分词：中文无空格，`question.split()` 会把整句当一个 token，
    永远匹配不到类别别名。直接对整句做子串包含。
    """
    if not question:
        return False
    for _, aliases in _PREFERENCE_CATEGORIES:
        for alias in aliases:
            if alias and alias in question:
                return True
    return False


def has_similar_intent(question: str) -> bool:
    """判断问题是否表达了"想要类似/同类推荐"的意图（如「推荐两个类似的」）。

    这类问题已足够具体（用户要的是与当前观看/上文相关的同类内容），
    不需要追问偏好类别。
    """
    if not question:
        return False
    return any(kw in question for kw in _SIMILAR_INTENT_KEYWORDS)


class IntentClarifier:
    """
    意图澄清器：根据上下文判断是否需要追问用户。
    规则触发，不调 LLM。
    """

    @staticmethod
    def need_clarification(
        intent: str,
        user_id: Optional[str] = None,
        user_preference: Optional[Dict[str, Any]] = None,
        video_id: Optional[str] = None,
        mentioned_keywords: Optional[List[str]] = None,
        question: Optional[str] = None,
    ) -> bool:
        """
        判断是否需要追问。

        Args:
            intent: 路由结果 (recommend / video_qa / user_data / chat)
            user_id: 用于查偏好记忆
            user_preference: 用户偏好 dict（直接传入，避免重复查 DB）
            video_id: 当前视频上下文
            mentioned_keywords: 问题中提取的关键词（用于判断歧义）
            question: 原始问题。用于判断是否已写明偏好类别（推荐意图）

        Returns:
            True 表示应该追问
        """
        # recommend：新用户 + 无偏好记忆 → 追问
        # 但问题已写明类别（「推荐科技类的」）或表达了相似意图（「推荐两个类似的」、
        # 「像这个的」）时不再追问，直接让推荐流程跑（画像/query 会用这些关键词）。
        if intent == WorkflowType.RECOMMEND:
            has_pref = bool(user_preference and (
                user_preference.get("favorite_tags")
                or user_preference.get("favorite_video_ids")
                or user_preference.get("liked_video_ids")
            ))
            if not has_pref and (
                has_category_keyword(question or "") or has_similar_intent(question or "")
            ):
                return False
            if not has_pref:
                return True

        # video_qa：缺 video_id → 追问
        if intent == WorkflowType.VIDEO_QA and not video_id:
            return True

        # chat：仅空泛招呼（你好/在吗）且无实质功能诉求 → 引导
        # 中文不能靠 question.split() 判断"有无关键词"（整句一个 token），
        # 改为直接对问题做子串匹配：命中空泛招呼词且问题很短（≤8 字）才追问。
        if intent == WorkflowType.CHAT and not mentioned_keywords:
            q = (question or "").strip()
            if any(g in q for g in _VAGUE_GREETINGS) and len(q) <= 8:
                return True
            return False

        return False

    @staticmethod
    def get_clarification(
        intent: str,
        video_id: Optional[str] = None,
        mentioned_keywords: Optional[List[str]] = None,
        has_history: bool = False,
    ) -> str:
        """
        生成追问话术。
        返回纯文本，前端可以直接发给用户。
        """
        if intent == WorkflowType.RECOMMEND:
            if has_history:
                return _CLARIFICATIONS["recommend_no_history"].format(
                    categories=_format_categories(),
                )
            return _CLARIFICATIONS["recommend_new_user"].format(
                categories=_format_categories(),
            )

        if intent == WorkflowType.VIDEO_QA:
            if mentioned_keywords:
                kw = mentioned_keywords[0] if mentioned_keywords else "这个"
                return _CLARIFICATIONS["video_qa_ambiguous"].format(keyword=kw)
            return _CLARIFICATIONS["video_qa_no_id"]

        if intent == WorkflowType.CHAT:
            return _CLARIFICATIONS["chat_vague_platform"]

        return "能再具体描述一下你的需求吗？"

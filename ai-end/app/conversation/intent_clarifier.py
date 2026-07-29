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
from typing import Dict, Any, Optional, List

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
    ) -> bool:
        """
        判断是否需要追问。

        Args:
            intent: 路由结果 (recommend / video_qa / user_data / chat)
            user_id: 用于查偏好记忆
            user_preference: 用户偏好 dict（直接传入，避免重复查 DB）
            video_id: 当前视频上下文
            mentioned_keywords: 问题中提取的关键词（用于判断歧义）

        Returns:
            True 表示应该追问
        """
        # recommend：新用户 + 无偏好记忆 → 追问
        if intent == "recommend":
            has_pref = bool(user_preference and (
                user_preference.get("favorite_tags")
                or user_preference.get("favorite_video_ids")
                or user_preference.get("liked_video_ids")
            ))
            if not has_pref:
                return True

        # video_qa：缺 video_id → 追问
        if intent == "video_qa" and not video_id:
            return True

        # chat：模糊平台问题（无具体关键词） → 引导
        if intent == "chat" and not mentioned_keywords:
            return True

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
        if intent == "recommend":
            if has_history:
                return _CLARIFICATIONS["recommend_no_history"].format(
                    categories=_format_categories(),
                )
            return _CLARIFICATIONS["recommend_new_user"].format(
                categories=_format_categories(),
            )

        if intent == "video_qa":
            if mentioned_keywords:
                kw = mentioned_keywords[0] if mentioned_keywords else "这个"
                return _CLARIFICATIONS["video_qa_ambiguous"].format(keyword=kw)
            return _CLARIFICATIONS["video_qa_no_id"]

        if intent == "chat":
            return _CLARIFICATIONS["chat_vague_platform"]

        return "能再具体描述一下你的需求吗？"

    @staticmethod
    def extract_preference_from_reply(reply: str) -> Optional[str]:
        """
        从用户对追问的回复中提取偏好。
        例如用户回复"科技"或"我喜欢科技类" → 返回 "科技"。

        用于：用户在追问后直接选了类别 → 立即存为偏好记忆。
        """
        reply_lower = reply.strip().lower()
        if not reply_lower:
            return None

        # 1. 完全匹配
        for name, _ in _PREFERENCE_CATEGORIES:
            if name in reply:
                return name

        # 2. 关键词匹配
        for name, kws in _PREFERENCE_CATEGORIES:
            for kw in kws:
                if kw in reply:
                    return name

        return None
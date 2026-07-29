"""
工作流类型枚举 —— 消除 121 处 hardcode 字符串

所有 workflow 标识、tool sandbox 白名单、agent 列表都从这里取。
新增 / 重命名 workflow 只需改这里一处。
"""
from typing import List


class WorkflowType:
    VIDEO_QA = "video_qa_workflow"
    RECOMMEND = "recommend_workflow"
    USER_DATA = "user_data_workflow"
    CHAT = "chat_workflow"
    ROUTER = "router"

    @classmethod
    def all(cls) -> List[str]:
        return [cls.VIDEO_QA, cls.RECOMMEND, cls.USER_DATA, cls.CHAT]

    @classmethod
    def with_router(cls) -> List[str]:
        return cls.all() + [cls.ROUTER]


class ToolName:
    """工具名常量，与 ToolRegistry 中注册名一致"""
    VECTOR_SEARCH = "vector_search"
    RETRIEVE_KNOWLEDGE = "retrieve_knowledge"
    GET_VIDEO_INFO = "get_video_info"
    QUERY_USER_DATA = "query_user_data"
    RECOMMEND_VIDEOS = "recommend_videos"
    CLASSIFY_INTENT = "classify_intent"

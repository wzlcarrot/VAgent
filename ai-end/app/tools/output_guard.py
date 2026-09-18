"""
output_guard — 全局兜底消息常量

各 workflow / supervisor / router 共用的用户侧错误提示。
"""

FALLBACK_RESPONSE = "抱歉，我暂时无法处理这个请求，请稍后重试。"
SERVER_ERROR_MSG = "抱歉，服务器处理出错，请稍后重试。"
NO_RECOMMENDATION_MSG = "抱歉，暂时没有找到合适的推荐。"
ALL_AGENTS_FAILED_MSG = "抱歉，所有 Agent 都执行失败了。"
LLM_UNAVAILABLE_MSG = "抱歉，我现在无法回答这个问题，请稍后重试。"
VIDEO_QA_INSUFFICIENT_MSG = (
    "我在当前视频的资料里没有找到足够依据来回答这个问题。"
    "你可以换个说法，或问得更具体一些（例如结合视频标题里的关键词）。"
)
VIDEO_QA_NOT_INDEXED_MSG = (
    "该视频的知识库还在构建中，暂时无法基于片内内容准确回答。"
    "请稍后再试，或先观看视频简介与标签；平台会在转码完成后自动建立索引。"
)

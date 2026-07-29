"""
output_guard — 全局兜底消息常量

各 workflow / supervisor / router 共用的用户侧错误提示。
"""

FALLBACK_RESPONSE = "抱歉，我暂时无法处理这个请求，请稍后重试。"
SERVER_ERROR_MSG = "抱歉，服务器处理出错，请稍后重试。"
NO_RECOMMENDATION_MSG = "抱歉，暂时没有找到合适的推荐。"
ALL_AGENTS_FAILED_MSG = "抱歉，所有 Agent 都执行失败了。"
LLM_UNAVAILABLE_MSG = "抱歉，我现在无法回答这个问题，请稍后重试。"

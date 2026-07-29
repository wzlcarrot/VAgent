"""
app.exceptions —— 统一异常体系

提供分层的异常类，便于错误追踪和处理。

异常层级:
    AgentBaseException
    ├── ToolCallException          # 工具调用失败
    │   ├── ToolCallLimitExceeded  # 调用次数超限（别名）
    │   └── ToolCallTimeout        # 调用超时（别名）
    ├── ToolAccessDenied           # 沙箱拒绝
    ├── WorkflowException          # Workflow 执行失败
    │   ├── RouterException        # 路由失败
    │   └── SupervisorException    # 仲裁失败
    ├── DatabaseException          # 数据库操作失败
    ├── CacheException             # 缓存操作失败
    └── LLMException               # LLM 调用失败
"""

from typing import Optional, Any, Dict


class AgentBaseException(Exception):
    """Agent 系统基础异常"""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "details": self.details,
        }


class ToolCallException(AgentBaseException):
    """工具调用失败"""

    def __init__(
        self,
        tool_name: str,
        message: str,
        session_id: Optional[str] = None,
        agent: Optional[str] = None,
    ):
        super().__init__(message, {
            "tool_name": tool_name,
            "session_id": session_id,
            "agent": agent,
        })
        self.tool_name = tool_name
        self.session_id = session_id
        self.agent = agent


class ToolCallLimitExceeded(ToolCallException):
    """工具调用次数超限"""

    def __init__(self, tool_name: str, current: int, limit: int, **kwargs):
        message = f"工具 '{tool_name}' 调用超限: {current}/{limit}"
        super().__init__(tool_name, message, **kwargs)
        self.current = current
        self.limit = limit


class ToolCallTimeout(ToolCallException):
    """工具调用超时"""

    def __init__(self, tool_name: str, timeout: float, **kwargs):
        message = f"工具 '{tool_name}' 调用超时: {timeout}s"
        super().__init__(tool_name, message, **kwargs)
        self.timeout = timeout


class ToolAccessDenied(ToolCallException):
    """沙箱拒绝：Agent 无权调用该工具"""

    def __init__(self, tool_name: str, agent: str, **kwargs):
        message = f"沙箱拒绝: agent '{agent}' 无权调用工具 '{tool_name}'"
        super().__init__(tool_name, message, agent=agent, **kwargs)


class WorkflowException(AgentBaseException):
    """Workflow 执行失败"""

    def __init__(self, workflow_type: str, message: str, **kwargs):
        super().__init__(message, {"workflow_type": workflow_type, **kwargs})
        self.workflow_type = workflow_type


class RouterException(WorkflowException):
    """路由失败"""

    def __init__(self, message: str, question: Optional[str] = None, **kwargs):
        super().__init__("router", message, question=question, **kwargs)


class SupervisorException(WorkflowException):
    """仲裁失败"""

    def __init__(self, message: str, results: Optional[list] = None, **kwargs):
        super().__init__("supervisor", message, results=results, **kwargs)


class DatabaseException(AgentBaseException):
    """数据库操作失败"""

    def __init__(self, message: str, operation: Optional[str] = None, **kwargs):
        super().__init__(message, {"operation": operation, **kwargs})
        self.operation = operation


class CacheException(AgentBaseException):
    """缓存操作失败"""

    def __init__(self, message: str, key: Optional[str] = None, **kwargs):
        super().__init__(message, {"key": key, **kwargs})
        self.key = key


class LLMException(AgentBaseException):
    """LLM 调用失败"""

    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        status_code: Optional[int] = None,
        **kwargs,
    ):
        super().__init__(message, {
            "provider": provider,
            "status_code": status_code,
            **kwargs,
        })
        self.provider = provider
        self.status_code = status_code

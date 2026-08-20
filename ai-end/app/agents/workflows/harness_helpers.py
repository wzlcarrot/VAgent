"""
Harness helpers —— 各 workflow 共用的 checkpoint + governor 入口

提供：
- @checkpoint(step_name) decorator：自动从 state 读 session_id，从函数所在模块推断 workflow_type
- invoke_with_governor：工具调用 + 限流 + 超时
"""
import logging
from functools import wraps
from typing import Any, Callable, Dict

from app.agents.workflows.constants import WorkflowType
from app.config import settings
from app.exceptions import ToolCallLimitExceeded, ToolCallTimeout
from app.harness.checkpoint import Checkpoint, CheckpointManager
from app.harness.tool_governor import ToolGovernor

logger = logging.getLogger(__name__)

HARNESS_ENABLED = settings.harness_enabled


def save_checkpoint(
    session_id: str,
    workflow_type: str,
    step_name: str,
    state: Dict[str, Any],
    result: Dict[str, Any] = None,
    status: str = "completed",
    error: str = None,
):
    if not HARNESS_ENABLED or not session_id:
        return
    try:
        merged = {**(state or {}), **(result or {})}
        cp = Checkpoint(
            session_id=session_id,
            workflow_type=workflow_type,
            step_name=step_name,
            state_snapshot=merged,
            status=status,
            error=error,
        )
        CheckpointManager().save(cp)
    except Exception as e:
        logger.warning(f"checkpoint save failed for {step_name}: {e}")


def _infer_workflow_type(func) -> str:
    """从函数所在模块名推断 workflow_type"""
    module = func.__module__ or ""
    if "chat_graph" in module:
        return WorkflowType.CHAT
    if "video_qa" in module:
        return WorkflowType.VIDEO_QA
    if "recommend" in module:
        return WorkflowType.RECOMMEND
    if "user_data" in module:
        return WorkflowType.USER_DATA
    return module.split(".")[-1]


def checkpoint(step_name: str):
    """
    Decorator：节点执行后自动落 checkpoint。

    Usage:
        @checkpoint("faq_node")
        def _faq_node(state: ChatState) -> dict:
            ...

    从 state 自动读 session_id，从函数所在模块自动推断 workflow_type。
    """
    def decorator(func: Callable) -> Callable:
        workflow_type = _infer_workflow_type(func)

        @wraps(func)
        def wrapper(state, *args, **kwargs):
            sid = (state or {}).get("session_id", "")
            try:
                result = func(state, *args, **kwargs)
                if HARNESS_ENABLED and sid:
                    save_checkpoint(
                        session_id=sid,
                        workflow_type=workflow_type,
                        step_name=step_name,
                        state=state,
                        result=result if isinstance(result, dict) else {"result": result},
                    )
                return result
            except Exception as e:
                if HARNESS_ENABLED and sid:
                    save_checkpoint(
                        session_id=sid,
                        workflow_type=workflow_type,
                        step_name=step_name,
                        state=state,
                        status="failed",
                        error=str(e),
                    )
                raise

        return wrapper
    return decorator


def invoke_with_governor(
    session_id: str,
    agent: str,
    tool_name: str,
    fn: Callable,
):
    from app.utils.task_cancel import WorkflowCancelled, check_cancelled
    try:
        check_cancelled()
    except WorkflowCancelled:
        logger.info(f"tool {tool_name} skipped: workflow cancelled")
        return []
    if not HARNESS_ENABLED or not session_id:
        return fn()
    try:
        result = ToolGovernor().gate(
            session_id=session_id,
            agent=agent,
            tool_name=tool_name,
            arguments={},
            execute_fn=fn,
            record_artifact=True,
        )
        # before_tool_call 拦截钩子可能返回 None：兜底为空结果，避免破坏 workflow
        return result if result is not None else []
    except ToolCallLimitExceeded:
        logger.warning(f"tool {tool_name} hit limit, fallback to empty")
        return []
    except ToolCallTimeout as e:
        logger.warning(f"tool {tool_name} timeout: {e}")
        return []

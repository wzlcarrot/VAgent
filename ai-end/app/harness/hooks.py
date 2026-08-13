"""
Hook 引擎（借鉴 kimi-cli 的 hooks 体系，Agent Harness 的最后一块拼图）

事件驱动治理：在关键节点（工具调用、消息收发）前后触发钩子，
用于审计、日志、附加校验/拦截，与 Checkpoint / ToolGovernor / Sandbox 组成完整治理链。

- HookEvent: 事件类型常量
- HooksManager: 注册 / 触发钩子（支持可拦截的 bool 语义 + 可扩展 context 的 dict 语义）

钩子函数签名：
- 拦截型（before_*）：fn(context: dict) -> bool，返回 False 拒绝继续
- 观察型（after_*）：fn(context: dict) -> None 或返回 dict 合并进 context

线程安全：钩子在启动期注册，运行期只读触发（读多写少，无需锁）。
"""
import logging
from collections import defaultdict
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)


class HookEvent:
    """支持的事件类型。"""

    BEFORE_TOOL_CALL = "before_tool_call"
    AFTER_TOOL_CALL = "after_tool_call"
    BEFORE_MESSAGE = "before_message"
    AFTER_MESSAGE = "after_message"

    @classmethod
    def all(cls) -> List[str]:
        return [
            cls.BEFORE_TOOL_CALL,
            cls.AFTER_TOOL_CALL,
            cls.BEFORE_MESSAGE,
            cls.AFTER_MESSAGE,
        ]


# 拦截型钩子：返回 False 表示拒绝
InterceptHook = Callable[[Dict[str, Any]], bool]
# 观察型钩子：返回 None 或 dict（合并进 context）
ObserveHook = Callable[[Dict[str, Any]], Any]


class HooksManager:
    """注册与触发钩子。"""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._hooks: Dict[str, List[Callable]] = defaultdict(list)

    def register(self, event: str, fn: Callable) -> None:
        """注册一个钩子到指定事件。"""
        if event not in HookEvent.all():
            logger.warning(f"未知 hook 事件: {event}（忽略注册）")
            return
        self._hooks[event].append(fn)
        logger.debug(f"已注册 hook: {event} <- {getattr(fn, '__name__', fn)}")

    def trigger(self, event: str, **context: Any) -> Dict[str, Any]:
        """触发观察型钩子，返回合并后的 context。"""
        if not self.enabled:
            return dict(context)
        ctx = dict(context)
        for fn in self._hooks.get(event, []):
            try:
                result = fn(ctx)
                if isinstance(result, dict):
                    ctx.update(result)
            except Exception as e:
                logger.error(f"hook {event} 执行异常: {e}")
        return ctx

    def trigger_intercept(self, event: str, **context: Any) -> bool:
        """触发拦截型钩子，任一返回 False 即拒绝。"""
        if not self.enabled:
            return True
        ctx = dict(context)
        for fn in self._hooks.get(event, []):
            try:
                if fn(ctx) is False:
                    logger.info(f"hook {event} 拦截: {getattr(fn, '__name__', fn)} 返回 False")
                    return False
            except Exception as e:
                logger.error(f"hook {event} 执行异常: {e}")
        return True

    def has_hooks(self, event: str) -> bool:
        return bool(self._hooks.get(event))

    def clear(self) -> None:
        self._hooks.clear()


# 全局单例：启动期注册钩子，运行期触发
hooks_manager = HooksManager()

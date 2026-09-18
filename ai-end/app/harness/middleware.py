"""
轻量 middleware / waterfall 扩展点（借鉴 deepseek-harness 的插件式扩展）。

动机：给核心流程加行为（审计 / 改写 / 脱敏 / 限流 / 短路）时，**不改核心循环**，
只往命名扩展点挂中间件即可。相比 hooks（发出即忘），waterfall 支持"环绕"——
中间件可以调用 `next()` 继续、或直接返回以短路。

用法：
    from app.harness.middleware import tool_before
    def audit(payload, next_):
        log(payload["tool"])
        return next_()
    tool_before.use(audit)
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

Handler = Callable[[Dict[str, Any], Callable[[], Any]], Any]


class Waterfall:
    """同步中间件链：每个 handler 收到 (payload, next_)，可调 next_() 或短路返回。"""

    def __init__(self, name: str):
        self.name = name
        self._handlers: List[Handler] = []

    def use(self, fn: Handler) -> Handler:
        self._handlers.append(fn)
        return fn

    def clear(self) -> None:
        self._handlers.clear()

    @property
    def handlers(self) -> List[Handler]:
        return list(self._handlers)

    def run(self, payload: Dict[str, Any], terminal: Callable[[], Any]) -> Any:
        handlers = list(self._handlers)

        def dispatch(i: int) -> Any:
            if i >= len(handlers):
                return terminal()
            return handlers[i](payload, lambda: dispatch(i + 1))

        return dispatch(0)


# 命名扩展点（默认空 → 行为不变，零回归）
tool_before = Waterfall("tool/before")   # 工具执行前：可审计 / 改写 arguments / 短路
tool_after = Waterfall("tool/after")     # 工具结果投影后：可脱敏 / 改写返回

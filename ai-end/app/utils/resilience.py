"""
错误恢复工具
- 流式中途断网：客户端 disconnect 时清理 LLM 连接
- Token 过期：401 时清理客户端 token
- Redis 挂：降级到内存 dict
- LLM 失败：指数退避重试（已有）+ 熔断器
"""
import asyncio
import logging
import time
from typing import Callable, Any, Optional

logger = logging.getLogger(__name__)


# ─── 熔断器 ───
class CircuitBreaker:
    """
    简单熔断器：失败 N 次后熔断，timeout 后半开
    """
    def __init__(self, name: str, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time: Optional[float] = None
        self.state = "closed"  # closed | open | half-open
        self._lock = asyncio.Lock()
        self._update_gauge()

    def _update_gauge(self):
        try:
            from app.utils.metrics import circuit_breaker_state
            state_map = {"closed": 0, "open": 1, "half-open": 2}
            circuit_breaker_state.labels(service=self.name).set(state_map.get(self.state, 0))
        except Exception:
            pass

    async def call(self, fn: Callable, *args, **kwargs) -> Any:
        async with self._lock:
            if self.state == "open":
                if self.last_failure_time and time.time() - self.last_failure_time > self.recovery_timeout:
                    logger.info(f"熔断器 {self.name}: 尝试恢复 (half-open)")
                    self.state = "half-open"
                    self._update_gauge()
                else:
                    raise CircuitOpenError(f"熔断器 {self.name} 处于打开状态")

        try:
            result = await fn(*args, **kwargs) if asyncio.iscoroutinefunction(fn) else fn(*args, **kwargs)
        except Exception as e:
            async with self._lock:
                self.failures += 1
                self.last_failure_time = time.time()
                if self.failures >= self.failure_threshold:
                    self.state = "open"
                    logger.warning(f"熔断器 {self.name}: 已打开 (失败 {self.failures} 次)")
                self._update_gauge()
            raise
        else:
            async with self._lock:
                if self.state == "half-open":
                    logger.info(f"熔断器 {self.name}: 恢复成功")
                self.failures = 0
                self.state = "closed"
                self._update_gauge()
            return result

    def get_state(self) -> str:
        return self.state


class CircuitOpenError(Exception):
    pass


# ─── 客户端 disconnect 检测 ───
class DisconnectChecker:
    """
    包装异步生成器，检测客户端是否提前 disconnect
    is_disconnected 必须是返回 bool 的同步函数，或返回 coroutine 的异步函数
    """
    def __init__(self, is_disconnected):
        import inspect
        self.is_disconnected = is_disconnected
        self.is_async = inspect.iscoroutinefunction(is_disconnected)

    async def check(self) -> bool:
        """返回 True 表示客户端已断开（async 版）"""
        if self.is_async:
            try:
                result = await self.is_disconnected()
            except Exception:
                return False
        else:
            result = self.is_disconnected()
        if result:
            try:
                from app.utils.metrics import streaming_failures_total
                streaming_failures_total.labels(
                    endpoint="chat_stream", failure_type="client_disconnect"
                ).inc()
            except Exception:
                pass
            return True
        return False
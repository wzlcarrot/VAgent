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
from typing import Callable, Any, Optional, Dict
from functools import wraps

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


# ─── 全局熔断器实例 ───
llm_breaker = CircuitBreaker("llm", failure_threshold=5, recovery_timeout=30.0)
db_breaker = CircuitBreaker("db", failure_threshold=10, recovery_timeout=10.0)
redis_breaker = CircuitBreaker("redis", failure_threshold=5, recovery_timeout=15.0)


# ─── 带重试的异步执行 ───
async def retry_async(
    fn: Callable,
    *args,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 8.0,
    retryable_exceptions: tuple = (Exception,),
    operation_name: str = "unknown",
    **kwargs
) -> Any:
    """
    指数退避重试

    Usage:
        result = await retry_async(call_llm, messages, max_attempts=3)
    """
    from app.utils.metrics import recovery_attempts_total
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            if asyncio.iscoroutinefunction(fn):
                return await fn(*args, **kwargs)
            else:
                return fn(*args, **kwargs)
        except retryable_exceptions as e:
            last_exc = e
            if attempt >= max_attempts:
                recovery_attempts_total.labels(
                    operation=operation_name, outcome="exhausted"
                ).inc()
                logger.warning(f"{operation_name}: 重试 {attempt}/{max_attempts} 失败，已耗尽")
                raise
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            logger.info(f"{operation_name}: 第 {attempt} 次失败，{delay:.1f}s 后重试 (err={e})")
            recovery_attempts_total.labels(
                operation=operation_name, outcome="retrying"
            ).inc()
            await asyncio.sleep(delay)

    if last_exc:
        raise last_exc


# ─── Redis 降级包装 ───
class RedisFallback:
    """
    Redis 包装器：Redis 不可用时降级到内存 dict
    """
    def __init__(self, name: str = "default"):
        self.name = name
        self._memory_store: Dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._redis_unavailable = False
        self._last_check = 0.0

    async def get(self, key: str) -> Optional[Any]:
        # 优先 Redis
        try:
            if not self._redis_unavailable:
                r = await self._get_redis()
                if r is not None:
                    return r.get(key)
        except Exception as e:
            logger.warning(f"Redis {self.name} 读失败，降级到内存: {e}")
            self._redis_unavailable = True
            self._last_check = time.time()
            try:
                from app.utils.metrics import streaming_failures_total
                streaming_failures_total.labels(endpoint="redis", failure_type="get").inc()
            except Exception:
                pass

        # 内存降级
        async with self._lock:
            return self._memory_store.get(key)

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        # 优先 Redis
        try:
            if not self._redis_unavailable:
                r = await self._get_redis()
                if r is not None:
                    if ttl:
                        r.setex(key, ttl, value)
                    else:
                        r.set(key, value)
                    return True
        except Exception as e:
            logger.warning(f"Redis {self.name} 写失败，降级到内存: {e}")
            self._redis_unavailable = True
            self._last_check = time.time()
            try:
                from app.utils.metrics import streaming_failures_total
                streaming_failures_total.labels(endpoint="redis", failure_type="set").inc()
            except Exception:
                pass

        # 内存降级
        async with self._lock:
            self._memory_store[key] = value
        return True

    async def delete(self, key: str) -> bool:
        try:
            if not self._redis_unavailable:
                r = await self._get_redis()
                if r is not None:
                    r.delete(key)
        except Exception:
            pass
        async with self._lock:
            self._memory_store.pop(key, None)
        return True

    async def _get_redis(self):
        """延迟取 Redis 客户端"""
        try:
            from app.tools.context_tools import _get_redis as ctx_redis
            return ctx_redis()
        except Exception:
            return None

    def health(self) -> dict:
        return {
            "redis_available": not self._redis_unavailable,
            "memory_keys": len(self._memory_store),
            "last_check": self._last_check,
        }


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
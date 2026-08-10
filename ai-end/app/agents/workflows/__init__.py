import asyncio
import atexit
import concurrent.futures
import logging
from typing import Callable

logger = logging.getLogger(__name__)


def _executor_workers() -> int:
    """线程池并发数：优先配置，默认按 CPU 核数*2，下限 4。"""
    try:
        from app.config import settings
        return max(4, settings.agent_async_max_workers)
    except Exception:
        import os
        return max(4, (os.cpu_count() or 4) * 2)


_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=_executor_workers(), thread_name_prefix="agent_async"
)
# atexit 注册兜底关闭（lifespan 没显式关闭时也保证清理）
atexit.register(lambda: _executor.shutdown(wait=False))


async def run_sync_in_executor(fn: Callable, *args, timeout: float = None, **kwargs):
    """在线程池中执行同步函数，可选超时。

    timeout：超过后取消等待（coroutine 不再阻塞 event loop），
    底层线程会继续跑完但被丢弃——避免单个卡死的 workflow 永久占用线程池。
    """
    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(_executor, lambda: fn(*args, **kwargs))
    if timeout is not None:
        return await asyncio.wait_for(fut, timeout=timeout)
    return await fut


def shutdown_executor():
    """FastAPI lifespan 关闭时显式调用，避免 atexit 阶段的潜在问题"""
    try:
        _executor.shutdown(wait=False)
    except Exception as e:
        logger.debug(f"agent_async executor shutdown: {e}")

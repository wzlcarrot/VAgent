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

    timeout：超过后抛 asyncio.TimeoutError，set 取消 Event，并 abort 已注册的
    httpx.Client / psycopg2 connection.cancel，打断进行中的下游 I/O。
    线程本身无法被杀死；I/O 被掐断后工作函数应尽快返回。
    """
    import threading

    from app.utils.task_cancel import cancel_scope

    loop = asyncio.get_running_loop()
    cancel_event = threading.Event()

    def _wrapped():
        with cancel_scope(cancel_event):
            return fn(*args, **kwargs)

    fut = loop.run_in_executor(_executor, _wrapped)
    if timeout is None:
        return await fut
    try:
        return await asyncio.wait_for(fut, timeout=timeout)
    except asyncio.TimeoutError:
        cancel_event.set()
        from app.utils.task_cancel import abort_running_io
        abort_running_io(cancel_event)
        raise


def shutdown_executor():
    """FastAPI lifespan 关闭时显式调用，避免 atexit 阶段的潜在问题"""
    try:
        _executor.shutdown(wait=False)
    except Exception as e:
        logger.debug(f"agent_async executor shutdown: {e}")

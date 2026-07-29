import asyncio
import atexit
import concurrent.futures
import logging
from typing import Callable

logger = logging.getLogger(__name__)

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="agent_async")
# atexit 注册兜底关闭（lifespan 没显式关闭时也保证清理）
atexit.register(lambda: _executor.shutdown(wait=False))


async def run_sync_in_executor(fn: Callable, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, lambda: fn(*args, **kwargs))


def shutdown_executor():
    """FastAPI lifespan 关闭时显式调用，避免 atexit 阶段的潜在问题"""
    try:
        _executor.shutdown(wait=False)
    except Exception as e:
        logger.debug(f"agent_async executor shutdown: {e}")

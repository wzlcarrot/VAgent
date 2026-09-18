"""
长期记忆归档后台任务。

软失效（invalid_at）保留历史可追溯，但主表会持续增长。本任务定期把**失效超过保留期**
的记忆搬进 `user_memory_archive` 并从主表删除，保持召回表精简。

与 `_shared.py` 的 token 清理任务同构：start/stop 由 FastAPI lifespan 调用。
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

_task = None


async def _memory_archive_loop() -> None:
    from app.config import settings

    interval = max(60, int(settings.memory_archive_interval_seconds))
    while True:
        try:
            await asyncio.sleep(interval)
            if int(settings.memory_archive_after_days) <= 0:
                continue
            from app.agents.workflows import run_sync_in_executor
            from app.tools.memory_tools import MemoryTools

            archived = await run_sync_in_executor(MemoryTools.archive_invalid_memories)
            if archived:
                logger.info("memory archive task: archived=%d rows", archived)
        except asyncio.CancelledError:
            break
        except Exception as e:  # noqa: BLE001
            logger.debug(f"memory archive task 异常: {e}")


def start_memory_archive_task() -> None:
    global _task
    if _task is None:
        try:
            loop = asyncio.get_running_loop()
            _task = loop.create_task(_memory_archive_loop())
        except RuntimeError:
            pass


def stop_memory_archive_task() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None

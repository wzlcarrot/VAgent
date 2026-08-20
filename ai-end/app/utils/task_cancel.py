"""工作流超时取消：置位 Event，并中断进行中的 HTTP / DB。

Python 不能强制杀死线程。超时后会：
1. set Event，后续重试 / 工具入口立即退出
2. 调用已注册的 abortable（httpx.Client.close、psycopg2 connection.cancel），
   打断正在阻塞的下游 I/O，而不是空等 client/DB 自己的 timeout
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Callable, Iterator, List, Optional

_local = threading.local()
_closeables_lock = threading.Lock()
_closeables: dict[int, List[Callable[[], None]]] = {}


class WorkflowCancelled(Exception):
    """当前线程的 workflow 已被调用方超时取消。"""


def current_cancel_event() -> Optional[threading.Event]:
    return getattr(_local, "event", None)


def is_cancelled() -> bool:
    ev = current_cancel_event()
    return bool(ev is not None and ev.is_set())


def check_cancelled() -> None:
    if is_cancelled():
        raise WorkflowCancelled("workflow cancelled after timeout")


def interruptible_sleep(seconds: float) -> None:
    """可被取消打断的 sleep；取消时抛 WorkflowCancelled。"""
    import time
    ev = current_cancel_event()
    if ev is None:
        time.sleep(seconds)
        return
    if ev.wait(timeout=seconds):
        raise WorkflowCancelled("workflow cancelled during backoff")


def register_abortable(fn: Callable[[], None]) -> Callable[[], None]:
    """把 close/cancel 挂到当前 cancel Event 上。返回注销函数。

    若 Event 已置位（超时抢先发生），立即调用 fn，避免新启动的 I/O 漏取消。
    """
    ev = current_cancel_event()
    if ev is None:
        return lambda: None
    with _closeables_lock:
        already = ev.is_set()
        if not already:
            _closeables.setdefault(id(ev), []).append(fn)
    if already:
        try:
            fn()
        except Exception:
            pass
        return lambda: None

    def unregister() -> None:
        with _closeables_lock:
            bucket = _closeables.get(id(ev))
            if not bucket:
                return
            try:
                bucket.remove(fn)
            except ValueError:
                pass

    return unregister


def abort_running_io(event: threading.Event) -> None:
    """超时线程调用：关闭/取消该 workflow 已注册的下游 I/O。"""
    with _closeables_lock:
        fns = _closeables.pop(id(event), [])
    for fn in fns:
        try:
            fn()
        except Exception:
            pass


@contextmanager
def cancel_scope(event: threading.Event) -> Iterator[None]:
    prev = getattr(_local, "event", None)
    _local.event = event
    try:
        yield
    finally:
        abort_running_io(event)
        _local.event = prev

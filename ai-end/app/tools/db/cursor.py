"""
数据库游标 context manager

消除 30+ 处重复的 try/finally 模板：
    pool = cls._get_pool()
    if pool is None: return ...
    conn = pool.getconn()
    try:
        cursor = conn.cursor(...)
        cursor.execute(...)
        ...
    finally:
        pool.putconn(conn)
"""
import logging
from contextlib import contextmanager
from typing import Optional, Any
from psycopg2.extras import RealDictCursor
from app.tools.db.pool import get_global_pool

logger = logging.getLogger(__name__)


@contextmanager
def get_cursor(cursor_factory=RealDictCursor, commit: bool = False):
    """
    上下文管理器：自动管理 conn.getconn / putconn / 异常回滚。

    Usage:
        with get_cursor() as cursor:
            if cursor is None: return []
            cursor.execute(...)
            rows = cursor.fetchall()

        with get_cursor(commit=True) as cursor:
            cursor.execute("INSERT ...")

    注意：DB 不可用时 yield None，调用方需判断。

    异常处理：
    - 用户代码异常 → rollback → 关闭 conn（不还 pool，因为状态可能损坏）
    - rollback 自身失败 → 关闭 conn（不还 pool）
    - 正常完成 → commit（如果需要）→ putconn 还给 pool
    """
    pool = get_global_pool()
    if pool is None:
        yield None
        return
    conn = pool.getconn()
    cursor = None
    broken = False
    try:
        cursor = conn.cursor(cursor_factory=cursor_factory)
        yield cursor
        if commit:
            conn.commit()
    except Exception as e:
        broken = True
        try:
            conn.rollback()
        except Exception as rb_err:
            # rollback 失败意味着连接状态不可信，直接关闭（不还 pool）
            logger.error(f"DB rollback 失败，连接已损坏: {rb_err}")
            try:
                conn.close()
            except Exception:
                pass
            # 阻止 finally 里的 putconn
            conn = None
        logger.error(f"DB 操作失败: {e}")
        raise
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if conn is not None and not broken:
            # 只有未发生异常时才还连接给 pool
            try:
                pool.putconn(conn)
            except Exception:
                pass
        elif conn is not None:
            # 发生异常但 rollback 成功，连接可以还
            try:
                pool.putconn(conn)
            except Exception:
                pass


@contextmanager
def get_scalar():
    """获取单个标量值的简化包装"""
    with get_cursor(cursor_factory=None) as cursor:
        if cursor is None:
            yield None
            return
        yield cursor

"""
DB 工具函数

提供数据库连接管理的便捷工具。
"""

from contextlib import contextmanager
from typing import Generator
import psycopg2
from psycopg2.extras import RealDictCursor


@contextmanager
def get_db_connection(cursor_factory=RealDictCursor) -> Generator:
    """
    获取数据库连接的 context manager。

    自动处理连接的获取和释放，确保异常时也能正确归还连接池。

    Args:
        cursor_factory: 游标类型，默认 RealDictCursor

    Yields:
        (connection, cursor) 元组

    Example:
        >>> with get_db_connection() as (conn, cursor):
        ...     cursor.execute("SELECT 1")
        ...     result = cursor.fetchone()
    """
    from app.tools.db import get_global_pool

    pool = get_global_pool()
    if pool is None:
        raise RuntimeError("数据库连接池不可用")

    conn = pool.getconn()
    cursor = None
    try:
        cursor = conn.cursor(cursor_factory=cursor_factory)
        yield conn, cursor
    except Exception:
        # 出错时尝试回滚
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        pool.putconn(conn)


@contextmanager
def get_db_connection_raw() -> Generator:
    """
    获取原始数据库连接（不带 cursor）。

    适用于需要手动管理 cursor 的场景。

    Yields:
        connection 对象

    Example:
        >>> with get_db_connection_raw() as conn:
        ...     cursor = conn.cursor()
        ...     try:
        ...         cursor.execute("SELECT 1")
        ...     finally:
        ...         cursor.close()
    """
    from app.tools.db import get_global_pool

    pool = get_global_pool()
    if pool is None:
        raise RuntimeError("数据库连接池不可用")

    conn = pool.getconn()
    try:
        yield conn
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        pool.putconn(conn)

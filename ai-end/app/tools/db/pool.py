"""
PostgreSQL 连接池管理

提供全局 ThreadedConnectionPool，含健康检查。
- 启动时尝试建立连接
- 每次获取时先健康检查（每 30s 一次）
- 失败时降级（pool=None，调用方应处理）
"""
import logging
import time
from typing import Optional
from psycopg2 import pool
from app.config import settings

logger = logging.getLogger(__name__)

_global_pool: Optional[pool.ThreadedConnectionPool] = None
_last_health_check: float = 0.0
_health_check_interval: float = 30.0


def get_global_pool() -> Optional[pool.ThreadedConnectionPool]:
    """
    获取全局连接池。30 秒一次健康检查，失败则重建。
    """
    global _global_pool, _last_health_check
    if _global_pool is not None:
        now = time.time()
        if now - _last_health_check < _health_check_interval:
            return _global_pool
        try:
            conn = _global_pool.getconn()
            conn.ping()
            _global_pool.putconn(conn)
            _last_health_check = now
            return _global_pool
        except Exception:
            _global_pool = None
            _last_health_check = 0.0

    try:
        _global_pool = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=settings.db_pool_size,
            host=settings.pg_host,
            port=settings.pg_port,
            user=settings.pg_user,
            password=settings.pg_password,
            dbname=settings.pg_database,
        )
        _last_health_check = time.time()
        return _global_pool
    except Exception as e:
        logger.error(f"创建数据库连接池失败: {e}")
        return None


def close_global_pool():
    """关闭全局连接池（graceful shutdown 时调用）"""
    global _global_pool
    if _global_pool is not None:
        try:
            _global_pool.closeall()
        except Exception as e:
            logger.warning(f"关闭连接池失败: {e}")
        finally:
            _global_pool = None

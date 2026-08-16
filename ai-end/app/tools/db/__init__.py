"""
app.tools.db —— 数据库基础设施

子模块:
- pool: 全局连接池
- cursor: context manager
- schema: 启动时建表
"""
from app.tools.db.cursor import get_cursor
from app.tools.db.pool import close_global_pool, get_global_pool
from app.tools.db.schema import init_agent_tables

__all__ = [
    "get_global_pool",
    "close_global_pool",
    "get_cursor",
    "init_agent_tables",
]

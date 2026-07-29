# DEPRECATED: 此文件已废弃，ROUTER_TOOLS 已合并到 app.tools.tool_registry
# 保留此文件仅为兼容旧的 import path，新代码请用：
#   from app.tools.tool_registry import get_router_tool_schemas
from app.tools.tool_registry import get_router_tool_schemas

ROUTER_TOOLS = get_router_tool_schemas()
__all__ = ["ROUTER_TOOLS"]

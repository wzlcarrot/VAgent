"""
Tool Registry + Tool Sandbox

工具注册架构：集中式注册、按Agent隔离、权限校验

集成 Harness 治理：
- ToolGovernor: 调用次数限制、超时、trace
- 通过 invoke_with_governance() 入口统一调用
"""

import logging
from typing import Dict, Any, List, Optional, Callable

from app.agents.workflows.constants import WorkflowType

logger = logging.getLogger(__name__)


class Tool:
    def __init__(self, name: str, description: str, parameters: Dict,
                 execute_fn: Callable = None,
                 required_permissions: List[str] = None,
                 allowed_agents: List[str] = None,
                 public: bool = False):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.execute_fn = execute_fn
        self.required_permissions = required_permissions or []
        self.allowed_agents = allowed_agents or []
        # public=True 时任何 agent 都能调用；public=False（默认）则严格按 allowed_agents 白名单
        self.public = public

    def to_openai_schema(self) -> Dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }

    def execute(self, **kwargs) -> Any:
        # 本注册表不承载执行逻辑（见 init_registry 注释）。
        # 若未来需要统一执行入口，应在此绑定真实工具函数而非 stub。
        logger.warning(
            f"Tool.execute 被调用但未绑定执行函数: {self.name} "
            f"（真实执行应在 workflow 内直接调用工具类）"
        )
        return None


class ToolRegistry:
    _instance = None
    _tools: Dict[str, Tool] = {}
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def register(self, tool: Tool):
        if tool.name in self._tools:
            logger.warning(f"Tool '{tool.name}' 已注册，覆盖中")
        self._tools[tool.name] = tool
        logger.info(f"注册工具: {tool.name}")

    def get(self, name: str) -> Optional[Tool]:
        # 自动惰性初始化：避免漏调 init_registry 导致 sandbox 拒绝所有工具
        if not self._initialized:
            init_registry()
        return self._tools.get(name)

    def get_all_schemas(self, caller: str = None) -> List[Dict]:
        if caller:
            return [
                t.to_openai_schema()
                for t in self._tools.values()
                if ToolSandbox.validate_call(t.name, caller)
            ]
        return [t.to_openai_schema() for t in self._tools.values()]

    def list_tools(self) -> List[str]:
        return list(self._tools.keys())

    def unregister(self, name: str):
        self._tools.pop(name, None)


class ToolSandbox:
    @staticmethod
    def validate_call(tool_name: str, caller: str) -> bool:
        """
        沙箱校验：判断指定Agent能否调用指定工具。

        策略（deny by default）：
        - 工具不存在 → 拒绝
        - 工具标记 public=True → 允许
        - caller 在 allowed_agents 白名单中 → 允许
        - 其他一律拒绝（包括 allowed_agents 为空的情况）
        """
        registry = ToolRegistry()
        tool = registry.get(tool_name)
        if not tool:
            logger.warning(f"沙箱拦截: 工具 '{tool_name}' 不存在")
            return False
        if tool.public:
            return True
        if not tool.allowed_agents:
            logger.warning(
                f"沙箱拦截: 工具 '{tool_name}' 未配置 allowed_agents 且未标记 public，"
                f"拒绝 '{caller}' 的调用（deny by default）"
            )
            return False
        allowed = caller in tool.allowed_agents
        if not allowed:
            logger.warning(f"沙箱拦截: '{caller}' 无权调用 '{tool_name}'")
        return allowed

    @staticmethod
    def filter_schemas(schemas: List[Dict], caller: str) -> List[Dict]:
        """过滤出指定Agent可用的工具Schema"""
        registry = ToolRegistry()
        return [
            s for s in schemas
            if registry.get(s["function"]["name"])
            and ToolSandbox.validate_call(s["function"]["name"], caller)
        ]


_SPECS = [
    {
        "name": "get_video_info",
        "description": "获取指定视频的详细信息（标题、作者、时长、标签、简介等）",
        "parameters": {
            "type": "object",
            "properties": {
                "video_id": {"type": "string", "description": "视频ID"}
            },
            "required": ["video_id"]
        },
        "allowed_agents": [WorkflowType.VIDEO_QA],
    },
    {
        "name": "vector_search",
        "description": "基于向量相似度从知识库检索相关视频/文档（pgvector + Embedding）",
        "parameters": {
            "type": "object",
            "properties": {
                "query_vector": {"type": "array", "items": {"type": "number"}, "description": "查询向量"},
                "top_k": {"type": "integer", "description": "返回数量", "default": 10}
            },
            "required": ["query_vector"]
        },
        "allowed_agents": [WorkflowType.RECOMMEND, WorkflowType.VIDEO_QA],
    },
    {
        "name": "intent_classify",
        "description": "对用户数据查询的意图分类（最近/统计/排行/具体等）",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "查询文本"},
                "intent_type": {"type": "string", "description": "目标意图类型"}
            },
            "required": ["query"]
        },
        "allowed_agents": [WorkflowType.USER_DATA],
    },
    {
        "name": "user_data_query",
        "description": "查询用户个人数据（点赞/收藏/历史/投币/评论 等）",
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "用户ID"},
                "data_type": {"type": "string", "description": "数据类型"},
                "time_range": {"type": "string", "description": "时间范围"},
                "aggregation": {"type": "string", "description": "聚合方式"}
            },
            "required": ["user_id", "data_type"]
        },
        "allowed_agents": [WorkflowType.USER_DATA],
    },
    {
        "name": "query_user_data",
        "description": "查询用户个人数据（点赞数、收藏数、播放历史等）",
        "parameters": {
            "type": "object",
            "properties": {
                "data_type": {
                    "type": "string",
                    "enum": ["like", "favorite", "history", "coin", "comment"],
                    "description": "数据类型"
                },
                "time_range": {
                    "type": "string",
                    "enum": ["today", "week", "all"],
                    "description": "时间范围"
                },
                "aggregation": {
                    "type": "string",
                    "enum": ["count", "list", "top"],
                    "description": "聚合方式"
                }
            },
            "required": ["data_type", "time_range", "aggregation"]
        },
        "allowed_agents": [WorkflowType.USER_DATA],
    },
    {
        "name": "retrieve_knowledge",
        "description": "从知识库检索与查询相关的视频知识文档",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索查询"},
                "top_k": {"type": "integer", "description": "返回数量", "default": 3}
            },
            "required": ["query"]
        },
        "allowed_agents": [WorkflowType.VIDEO_QA, WorkflowType.CHAT],
    },
    {
        "name": "recommend_videos",
        "description": "基于用户偏好获取个性化视频推荐",
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "用户ID"},
                "count": {"type": "integer", "description": "推荐数量", "default": 5}
            },
            "required": ["user_id"]
        },
        "allowed_agents": [WorkflowType.RECOMMEND],
    },
    {
        "name": "classify_intent",
        "description": "对用户问题意图进行分类",
        "parameters": {
            "type": "object",
            "properties": {
                "intent_type": {
                    "type": "string",
                    "enum": [WorkflowType.VIDEO_QA, WorkflowType.RECOMMEND, WorkflowType.USER_DATA, WorkflowType.CHAT],
                    "description": "意图类型"
                }
            },
            "required": ["intent_type"]
        },
        "allowed_agents": [WorkflowType.ROUTER],
    },
]


def init_registry():
    """初始化并注册所有内置工具。

    本注册表只负责工具 schema 暴露（给 LLM function calling）和权限校验，
    不承担实际执行——真实执行在各 workflow 内直接调用工具类（VideoTools 等），
    避免 schema 与执行逻辑耦合导致的两处漂移。
    """
    registry = ToolRegistry()
    for spec in _SPECS:
        name = spec["name"]
        tool = Tool(
            name=name,
            description=spec["description"],
            parameters=spec["parameters"],
            allowed_agents=spec.get("allowed_agents", []),
        )
        registry.register(tool)
    registry._initialized = True
    logger.info(f"工具注册中心已初始化，共 {len(_SPECS)} 个工具")


def get_tool_schemas(caller: str = None) -> List[Dict]:
    """获取指定Agent可用的工具Schema列表"""
    registry = ToolRegistry()
    return registry.get_all_schemas(caller)


def check_tool_access(tool_name: str, caller: str) -> bool:
    """沙箱入口：检查工具是否允许被调用"""
    return ToolSandbox.validate_call(tool_name, caller)


def get_router_tool_schemas() -> List[Dict]:
    """路由器专用工具 schema（仅 classify_intent）"""
    return [
        s for s in get_tool_schemas(WorkflowType.ROUTER)
        if s["function"]["name"] == "classify_intent"
    ]


__all__ = [
    "Tool", "ToolRegistry", "ToolSandbox",
    "init_registry", "get_tool_schemas", "get_router_tool_schemas", "check_tool_access",
]

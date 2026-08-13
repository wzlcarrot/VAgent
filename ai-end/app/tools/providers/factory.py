"""Provider 工厂：按名称注册与获取 provider 实例。

新增 provider：继承 BaseProvider 后在 _REGISTRY 注册即可，
LLM_tools 与调用方零改动。
"""
from __future__ import annotations

from typing import Dict, Type

from app.tools.providers.base import BaseProvider
from app.tools.providers.deepseek import DeepSeekProvider
from app.tools.providers.minimax import MiniMaxProvider

_REGISTRY: Dict[str, Type[BaseProvider]] = {
    DeepSeekProvider.name: DeepSeekProvider,
    MiniMaxProvider.name: MiniMaxProvider,
}

_INSTANCES: Dict[str, BaseProvider] = {}


def provider_factory(name: str) -> BaseProvider:
    """获取 provider 实例（单例）。未知名称回退到 deepseek。"""
    cls = _REGISTRY.get(name or "", _REGISTRY.get("deepseek"))
    if cls is None:
        raise ValueError(f"Unknown provider: {name}")
    if cls.name not in _INSTANCES:
        _INSTANCES[cls.name] = cls()
    return _INSTANCES[cls.name]


def registered_providers() -> list:
    """已注册的 provider 名称列表。"""
    return list(_REGISTRY.keys())

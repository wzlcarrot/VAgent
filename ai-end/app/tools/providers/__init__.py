"""
Provider 抽象层（借鉴 Clawd-Code 的 BaseProvider 设计）

可插拔 LLM Provider 架构：
- BaseProvider: 抽象基类，定义 provider 配置解析与能力差异接口
- DeepSeekProvider / MiniMaxProvider: 具体实现
- provider_factory: 按名称注册/获取 provider

新增 provider 只需：
1. 继承 BaseProvider 实现 resolve() 与能力方法
2. 在 __init__.py 的 _REGISTRY 注册
3. 配置好对应环境变量，无需改动 LLM_tools 与调用方
"""
from app.tools.providers.base import BaseProvider, ProviderConfig
from app.tools.providers.deepseek import DeepSeekProvider
from app.tools.providers.minimax import MiniMaxProvider
from app.tools.providers.factory import provider_factory

__all__ = [
    "BaseProvider",
    "ProviderConfig",
    "DeepSeekProvider",
    "MiniMaxProvider",
    "provider_factory",
]

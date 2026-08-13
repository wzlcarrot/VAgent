"""BaseProvider 抽象基类：定义 LLM provider 的统一接口。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class ProviderConfig:
    """解析后的 provider 配置。"""

    base_url: str
    model: str
    api_key: str

    def as_tuple(self) -> tuple:
        return (self.base_url, self.model, self.api_key)


class BaseProvider(ABC):
    """LLM Provider 抽象基类。

    子类职责：
    - name: provider 标识（与 settings.llm_provider 对应）
    - resolve(): 从配置解析 (base_url, model, api_key)
    - supports_json_mode(): 是否支持 OpenAI 兼容的 response_format=json_object
    - build_payload_extra(): 注入 provider 特有的 payload 字段
    """

    name: str = ""

    @abstractmethod
    def resolve(self) -> ProviderConfig:
        """从配置解析 provider 参数。"""

    def supports_json_mode(self) -> bool:
        """是否支持 response_format=json_object（默认支持）。"""
        return True

    def build_payload_extra(self, payload: Dict, json_mode: bool = False) -> Dict:
        """注入 provider 特有 payload 字段（默认无）。"""
        return payload

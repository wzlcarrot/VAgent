"""DeepSeek Provider：标准 OpenAI 兼容接口。"""
from __future__ import annotations

from typing import Dict

from app.config import settings
from app.tools.providers.base import BaseProvider, ProviderConfig


class DeepSeekProvider(BaseProvider):
    name = "deepseek"

    def resolve(self) -> ProviderConfig:
        return ProviderConfig(
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            api_key=settings.deepseek_api_key,
        )

    def supports_json_mode(self) -> bool:
        # DeepSeek 兼容 OpenAI response_format=json_object
        return True

    def build_payload_extra(self, payload: Dict, json_mode: bool = False) -> Dict:
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

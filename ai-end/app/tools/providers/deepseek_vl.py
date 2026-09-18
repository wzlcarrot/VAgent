"""DeepSeek 多模态（Vision）Provider：deepseek-flash 支持图文混合输入。

DeepSeek Flash 原生支持图片输入（OpenAI 兼容的 image_url content block），
JSON 模式走原生 response_format=json_object，无需 prompt 前缀兜底。
旧的 deepseek-v4-flash-vision-exp 已退役，请求由最新 Flash 模型承接。
"""
from __future__ import annotations

from typing import Dict

from app.config import settings
from app.tools.providers.base import BaseProvider, ProviderConfig


class DeepSeekVLProvider(BaseProvider):
    name = "deepseek-vl"

    def resolve(self) -> ProviderConfig:
        return ProviderConfig(
            base_url=settings.deepseek_vl_base_url,
            model=settings.deepseek_vl_model,
            api_key=settings.effective_deepseek_vl_api_key,
        )

    def supports_json_mode(self) -> bool:
        # DeepSeek 兼容 OpenAI response_format=json_object
        return True

    def build_payload_extra(self, payload: Dict, json_mode: bool = False) -> Dict:
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

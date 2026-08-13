"""MiniMax Provider：多模态/视觉支持，JSON 模式走 prompt 指令而非 response_format。"""
from __future__ import annotations

from typing import Dict, List

from app.config import settings
from app.tools.providers.base import BaseProvider, ProviderConfig


class MiniMaxProvider(BaseProvider):
    name = "minimax"

    def resolve(self) -> ProviderConfig:
        return ProviderConfig(
            base_url=settings.minimax_base_url,
            model=settings.minimax_model,
            api_key=settings.minimax_api_key,
        )

    def supports_json_mode(self) -> bool:
        # MiniMax 不支持 OpenAI 的 response_format 字段（会 400）
        return False

    def build_payload_extra(self, payload: Dict, json_mode: bool = False) -> Dict:
        # json_mode 通过 prompt 指令约束（见 LLM_tools.chat_sync_json 的注入逻辑）
        return payload

    @staticmethod
    def json_mode_prompt_prefix() -> List[Dict]:
        """JSON 模式下注入的 system 指令（minimax 替代 response_format）。"""
        return [{
            "role": "system",
            "content": "你必须只输出一个合法的 JSON 对象，不要任何解释或 markdown 代码块包裹。",
        }]

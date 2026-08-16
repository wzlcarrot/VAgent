"""
Provider 抽象层测试：可插拔架构、配置解析、json_mode 能力差异
"""
from app.tools.providers import DeepSeekProvider, provider_factory
from app.tools.providers.base import ProviderConfig
from app.tools.providers.factory import registered_providers


class TestProviderRegistry:
    def test_registered_providers(self):
        names = registered_providers()
        assert "deepseek" in names
        assert "minimax" in names

    def test_factory_returns_singleton(self):
        a = provider_factory("deepseek")
        b = provider_factory("deepseek")
        assert a is b

    def test_factory_unknown_falls_back(self):
        # 未知 provider 回退 deepseek（不抛异常，兼容旧配置）
        p = provider_factory("unknown_provider")
        assert isinstance(p, DeepSeekProvider)

    def test_provider_config_type(self):
        cfg = provider_factory("deepseek").resolve()
        assert isinstance(cfg, ProviderConfig)
        assert cfg.base_url and cfg.model


class TestProviderCapabilities:
    def test_deepseek_supports_json_mode(self):
        assert provider_factory("deepseek").supports_json_mode() is True

    def test_minimax_not_supports_json_mode(self):
        """minimax 不支持 OpenAI response_format，走 prompt 指令"""
        assert provider_factory("minimax").supports_json_mode() is False

    def test_deepseek_payload_json_mode(self):
        p = provider_factory("deepseek")
        payload = p.build_payload_extra({"model": "m"}, json_mode=True)
        assert payload["response_format"] == {"type": "json_object"}

    def test_minimax_payload_json_mode_no_response_format(self):
        p = provider_factory("minimax")
        payload = p.build_payload_extra({"model": "m"}, json_mode=True)
        assert "response_format" not in payload

    def test_minimax_json_mode_prompt_prefix(self):
        prefix = provider_factory("minimax").json_mode_prompt_prefix()
        assert prefix[0]["role"] == "system"
        assert "JSON" in prefix[0]["content"]

    def test_llm_tools_resolve_delegates_to_provider(self):
        """LLM_tools._resolve_provider 委托 provider 工厂（门面）"""
        from app.tools import llm_tools
        base_url, model, api_key = llm_tools._resolve_provider("deepseek")
        assert base_url and model

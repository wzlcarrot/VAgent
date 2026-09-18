"""
Provider 抽象层测试：可插拔架构、配置解析、json_mode 能力差异
"""
from app.tools.providers import DeepSeekProvider, DeepSeekVLProvider, provider_factory
from app.tools.providers.base import ProviderConfig
from app.tools.providers.factory import registered_providers


class TestProviderRegistry:
    def test_registered_providers(self):
        names = registered_providers()
        assert "deepseek" in names
        assert "deepseek-vl" in names

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

    def test_deepseek_vl_provider_instance(self):
        assert isinstance(provider_factory("deepseek-vl"), DeepSeekVLProvider)


class TestProviderCapabilities:
    def test_deepseek_supports_json_mode(self):
        assert provider_factory("deepseek").supports_json_mode() is True

    def test_deepseek_vl_supports_json_mode(self):
        """DeepSeek 多模态同样兼容 OpenAI response_format"""
        assert provider_factory("deepseek-vl").supports_json_mode() is True

    def test_deepseek_payload_json_mode(self):
        p = provider_factory("deepseek")
        payload = p.build_payload_extra({"model": "m"}, json_mode=True)
        assert payload["response_format"] == {"type": "json_object"}

    def test_deepseek_vl_payload_json_mode(self):
        p = provider_factory("deepseek-vl")
        payload = p.build_payload_extra({"model": "m"}, json_mode=True)
        assert payload["response_format"] == {"type": "json_object"}

    def test_deepseek_vl_resolves_vision_model(self):
        """多模态 provider 指向 deepseek-flash（支持图文输入）"""
        cfg = provider_factory("deepseek-vl").resolve()
        assert cfg.base_url and cfg.model

    def test_deepseek_vl_api_key_falls_back_to_deepseek(self):
        """DEEPSEEK_VL_API_KEY 留空时回退主 DEEPSEEK_API_KEY"""
        from app.config import settings
        original_vl = settings.deepseek_vl_api_key
        original_ds = settings.deepseek_api_key
        try:
            settings.deepseek_vl_api_key = ""
            settings.deepseek_api_key = "sk-main-key"
            assert settings.effective_deepseek_vl_api_key == "sk-main-key"
            settings.deepseek_vl_api_key = "sk-vl-key"
            assert settings.effective_deepseek_vl_api_key == "sk-vl-key"
        finally:
            settings.deepseek_vl_api_key = original_vl
            settings.deepseek_api_key = original_ds

    def test_llm_tools_resolve_delegates_to_provider(self):
        """LLM_tools._resolve_provider 委托 provider 工厂（门面）"""
        from app.tools import llm_tools
        base_url, model, api_key = llm_tools._resolve_provider("deepseek")
        assert base_url and model

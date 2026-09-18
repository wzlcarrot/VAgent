"""微调意图分类模型接入路由的测试（mock 模型，不加载真模型）。"""
from unittest.mock import patch

from app.agents.router import Router
from app.agents.workflows.constants import WorkflowType


def test_router_uses_finetune_when_available():
    r = Router()
    with patch("app.config.settings.finetune_intent_enabled", True), \
         patch("app.config.settings.finetune_intent_confidence", 0.95), \
         patch("app.tools.finetune_intent.is_available", return_value=True), \
         patch("app.tools.finetune_intent.classify", return_value=WorkflowType.RECOMMEND):
        d = r._hybrid_route_full_impl("随便问一句")
    assert d.workflow_type == WorkflowType.RECOMMEND
    assert d.method == "finetune"
    assert d.confidence == 0.95


def test_router_falls_back_when_finetune_returns_none():
    r = Router()
    with patch("app.config.settings.finetune_intent_enabled", True), \
         patch("app.tools.finetune_intent.is_available", return_value=True), \
         patch("app.tools.finetune_intent.classify", return_value=None):
        d = r._hybrid_route_full_impl("怎么上传视频")
    assert d.method != "finetune"  # 回退到关键词/语义/LLM 路径


def test_router_skips_finetune_when_disabled():
    r = Router()
    with patch("app.config.settings.finetune_intent_enabled", False), \
         patch("app.tools.finetune_intent.classify") as mock_cls:
        r._hybrid_route_full_impl("怎么上传视频")
    mock_cls.assert_not_called()


def test_finetune_classify_returns_none_when_disabled():
    from app.tools import finetune_intent
    with patch("app.config.settings.finetune_intent_enabled", False):
        assert finetune_intent.classify("任意问题") is None
        assert finetune_intent.is_available() is False

"""search_channels 与 web stub 单测。"""
from unittest.mock import patch

from app.tools import search_channels as sc


def test_web_stub_empty():
    assert sc.web_search_stub("hello") == []


def test_active_channels_default():
    names = sc.active_channels()
    assert "keyword" in names
    assert "vector" in names
    assert "platform_docs" in names
    assert "web" not in names


def test_active_channels_with_web():
    with patch("app.config.settings.web_search_enabled", True):
        assert "web" in sc.active_channels()


def test_multi_channel_merges_channels():
    def kw(q, k, vid=None):
        return [{"content": "alpha", "score": 0.9}]

    def vec(q, k, vid=None):
        return [{"content": "alpha", "score": 0.8}, {"content": "beta", "score": 0.7}]

    with patch.dict(sc.CHANNEL_REGISTRY, {"keyword": kw, "vector": vec, "platform_docs": lambda *a, **k: []}), \
         patch.object(sc, "active_channels", return_value=["keyword", "vector"]):
        out = sc.multi_channel_recall("q", 5)
    assert len(out) == 2
    contents = {d["content"] for d in out}
    assert contents == {"alpha", "beta"}

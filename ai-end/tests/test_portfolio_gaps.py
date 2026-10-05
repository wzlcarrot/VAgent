from unittest.mock import MagicMock, patch

from app.agents.supervisor import Supervisor
from app.tools.output_guard import FALLBACK_RESPONSE
from app.tools.user_tools import _sql_on_today, _sql_on_week


def test_default_path_never_puts_web_in_video_qa():
    from app.runtime_path import describe_default_path

    d = describe_default_path()
    assert d["video_qa_uses_web"] is False
    assert d["orchestration_mode"] == "workflow"
    assert d["lock_default_path"] is True


def test_sql_today_is_shanghai_half_open_range():
    sql = _sql_on_today("action_time")
    assert "DATE(" not in sql
    assert "Asia/Shanghai" in sql
    assert "INTERVAL '1 day'" in sql


def test_sql_week_is_shanghai_week():
    sql = _sql_on_week("ua.action_time")
    assert "CURRENT_DATE" not in sql
    assert "Asia/Shanghai" in sql


def test_answer_usable_skips_empty_and_fallback():
    s = Supervisor()
    assert s.answer_usable("") is False
    assert s.answer_usable(FALLBACK_RESPONSE) is False
    assert s.answer_usable("你今天点赞了 3 次") is True
    assert s.answer_usable("", {"recommended_videos": [{"videoId": "v1"}]}) is True


def test_web_search_has_no_wikipedia_channel():
    from app.tools import search_channels as sc

    assert not hasattr(sc, "_search_wikipedia")
    assert "wikipedia" not in sc.CHANNEL_REGISTRY
    assert "wiki" not in sc.CHANNEL_REGISTRY


def test_web_search_merges_bing_and_baidu():
    from app.tools.search_channels import web_search

    bing = [{"title": "Bing 结果", "url": "https://bing.example/a", "content": "来自 Bing", "channel": "bing"}]
    baidu = [{"title": "百度结果", "url": "https://baidu.example/b", "content": "来自百度", "channel": "baidu"}]
    with patch("app.tools.search_channels._search_bing", return_value=bing), \
         patch("app.tools.search_channels._search_baidu", return_value=baidu):
        items = web_search("ViewHub", top_k=2)
    assert [i["channel"] for i in items] == ["bing", "baidu"]
    assert "duckduckgo" not in str(items).lower()
    assert "wikipedia" not in str(items).lower()


def test_baidu_parse_uses_mu_field():
    from app.tools.search_channels import parse_baidu_results

    html = (
        '{"mu":"https://news.example.com/py"}'
        '<span class="c-title-text">Python 教程</span>'
        '{"mu":"https://www.baidu.com/link?url=x"}'
    )
    items = parse_baidu_results(html, 3)
    assert len(items) == 1
    assert items[0]["url"] == "https://news.example.com/py"
    assert items[0]["channel"] == "baidu"


def test_video_recall_excludes_web_and_platform_docs():
    from app.tools.search_channels import active_channels

    assert active_channels("demo01") == ["keyword", "vector"]
    assert "web" in active_channels(None)


def test_bing_search_calls_microsoft_endpoint():
    from app.config import settings
    from app.tools.search_channels import _search_bing

    fake = MagicMock()
    fake.raise_for_status = MagicMock()
    fake.json.return_value = {
        "webPages": {"value": [{"name": "t", "url": "https://ex.com", "snippet": "s"}]}
    }
    with patch.object(settings, "bing_search_api_key", "k"), \
         patch.object(settings, "bing_search_endpoint", "https://api.bing.microsoft.com/v7.0/search"), \
         patch("httpx.get", return_value=fake) as get:
        items = _search_bing("ViewHub", 1)
    assert get.call_args.args[0] == "https://api.bing.microsoft.com/v7.0/search"
    assert items[0]["channel"] == "bing"


def test_baidu_search_uses_mu_html():
    from app.tools.search_channels import _search_baidu

    html = '{"mu":"https://news.example.com/py"}<span class="c-title-text">Python</span>'
    fake = MagicMock()
    fake.raise_for_status = MagicMock()
    fake.text = html
    with patch("httpx.get", return_value=fake):
        items = _search_baidu("python", 2)
    assert items[0]["url"] == "https://news.example.com/py"
    assert items[0]["channel"] == "baidu"


def test_web_search_empty_and_stub():
    from app.tools.search_channels import web_search, web_search_stub

    assert web_search("  ") == []
    with patch("app.tools.search_channels.web_search", return_value=[{"channel": "bing"}]) as w:
        assert web_search_stub("q", 1)[0]["channel"] == "bing"
        w.assert_called_once()


def test_web_channel_skips_when_video_scoped():
    from app.tools.search_channels import _web_channel

    assert _web_channel("q", 3, video_id="demo01") == []


def test_search_bing_without_key():
    from app.config import settings
    from app.tools.search_channels import _search_bing

    with patch.object(settings, "bing_search_api_key", ""):
        assert _search_bing("q", 3) == []


def test_keyword_channel_failure_returns_empty():
    from app.tools.search_channels import _keyword_channel

    with patch("app.tools.rag_tools.RAGTools.retrieve_knowledge", side_effect=RuntimeError("x")):
        assert _keyword_channel("q", 3) == []


def test_vector_and_docs_channel_failure_returns_empty():
    from app.tools.search_channels import _platform_docs_channel, _vector_channel

    with patch("app.tools.llm_tools.LLM_tools.embed", side_effect=RuntimeError("embed")):
        assert _vector_channel("q", 3) == []
    with patch("app.tools.rag_tools.RAGTools.retrieve_platform_docs", side_effect=RuntimeError("docs")):
        assert _platform_docs_channel("q", 3) == []

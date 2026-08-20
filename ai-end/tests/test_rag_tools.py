"""
RAG 检索/索引层测试：mock 连接池与 httpx，覆盖 BM25、向量、平台文档、索引。
无真实 DB / 网络。
"""
from unittest.mock import MagicMock, patch

from app.tools.rag_tools import (
    RAGTools,
    _char_bigrams,
    _has_chinese,
    _load_faq_cache_from_db,
    _search_faq,
    get_faq_cache,
    refresh_faq_cache,
)


def _pool_with_cursor(rows=None, rowcount=None, side_effect=None):
    conn = MagicMock()
    cursor = MagicMock()
    if side_effect is not None:
        cursor.execute.side_effect = side_effect
    cursor.fetchall.return_value = rows or []
    cursor.fetchone.return_value = rows[0] if rows else None
    if rowcount is not None:
        cursor.rowcount = rowcount
    conn.cursor.return_value = cursor
    pool = MagicMock()
    pool.getconn.return_value = conn
    return pool, conn, cursor


def test_has_chinese():
    assert _has_chinese("你好")
    assert not _has_chinese("hello")


def test_char_bigrams():
    bg = _char_bigrams(" 你好 ")
    assert "你好" in bg
    assert _char_bigrams("") == set()
    assert _char_bigrams("a") == set()


def test_is_available_no_pool():
    RAGTools._reset_available()
    with patch("app.tools.rag_tools.get_global_pool", return_value=None):
        assert RAGTools._is_available() is False


def test_is_available_with_pool():
    RAGTools._reset_available()
    pool = MagicMock()
    with patch("app.tools.rag_tools.get_global_pool", return_value=pool):
        assert RAGTools._is_available() is True


def test_retrieve_knowledge_no_pool():
    RAGTools._reset_available()
    with patch("app.tools.rag_tools.get_global_pool", return_value=None):
        assert RAGTools.retrieve_knowledge("q", 5) == []


def test_retrieve_knowledge_paradedb_success():
    RAGTools._reset_available()
    rows = [{"video_id": "v1", "video_name": "t", "introduction": "intro", "score": 2.5}]
    pool, conn, cursor = _pool_with_cursor(rows=rows)
    with patch("app.tools.rag_tools.get_global_pool", return_value=pool):
        out = RAGTools.retrieve_knowledge("q", 5)
    assert out[0]["video_id"] == "v1"
    assert out[0]["content"] == "intro"
    assert out[0]["block_type"] == "introduction"


def test_retrieve_knowledge_fallback_to_tsvector():
    RAGTools._reset_available()
    pool, conn, cursor = _pool_with_cursor(
        side_effect=[Exception("paradedb unavailable"), None],
    )
    # 第二次 cursor2 查询
    cursor2 = MagicMock()
    cursor2.fetchall.return_value = [{"video_id": "v2", "video_name": "n", "introduction": "", "score": 1.0}]
    conn.cursor.return_value = cursor2
    with patch("app.tools.rag_tools.get_global_pool", return_value=pool), \
         patch("app.tools.rag_tools._has_chinese", return_value=False):
        out = RAGTools.retrieve_knowledge("hello", 5)
    assert out[0]["video_id"] == "v2"
    assert out[0]["content"] == "n"  # introduction 空 → 用 video_name


def test_retrieve_knowledge_exception_returns_empty():
    RAGTools._reset_available()
    pool = MagicMock()
    pool.getconn.side_effect = RuntimeError("db down")
    with patch("app.tools.rag_tools.get_global_pool", return_value=pool):
        assert RAGTools.retrieve_knowledge("q", 5) == []


def test_vector_search_success():
    rows = [{"video_id": "v9", "video_name": "vec title", "introduction": "vec intro", "total_score": 0.8}]
    pool, conn, cursor = _pool_with_cursor(rows=rows)
    with patch("app.tools.rag_tools.get_global_pool", return_value=pool):
        out = RAGTools.vector_search([0.1, 0.2], 3)
    assert out[0]["video_id"] == "v9"
    assert out[0]["content"] == "vec intro"
    assert out[0]["block_type"] == "vector"


def test_vector_search_no_pool():
    with patch("app.tools.rag_tools.get_global_pool", return_value=None):
        assert RAGTools.vector_search([0.1], 3) == []


def test_vector_search_exception():
    pool = MagicMock()
    pool.getconn.side_effect = RuntimeError("x")
    with patch("app.tools.rag_tools.get_global_pool", return_value=pool):
        assert RAGTools.vector_search([0.1], 3) == []


def test_load_faq_cache_from_db_no_pool():
    with patch("app.tools.rag_tools.get_global_pool", return_value=None):
        assert _load_faq_cache_from_db() == []


def test_load_faq_cache_from_db_rows():
    pool, conn, cursor = _pool_with_cursor(
        rows=[{"title": "t", "content": "c", "type": "faq"}],
    )
    with patch("app.tools.rag_tools.get_global_pool", return_value=pool):
        out = _load_faq_cache_from_db()
    assert out[0]["title"] == "t"


def test_get_faq_cache_uses_db_then_fallback():
    from app.tools import rag_tools
    rag_tools._FAQ_CACHE = []
    rag_tools._FAQ_CACHE_LOADED_AT = 0.0
    with patch("app.tools.rag_tools._load_faq_cache_from_db", return_value=[{"title": "真实FAQ", "content": "内容", "type": "faq"}]):
        cache = get_faq_cache()
    assert cache and cache[0]["title"] == "真实FAQ"


def test_retrieve_platform_docs_memory_chinese():
    import time

    from app.tools import rag_tools
    rag_tools._FAQ_CACHE = [{"title": "如何登录", "content": "点右上角登录", "type": "guide"}]
    rag_tools._FAQ_CACHE_LOADED_AT = time.time()  # 避免 TTL 触发 DB 重载
    out = RAGTools.retrieve_platform_docs("如何登录", 3)
    assert out and out[0]["title"] == "如何登录"


def test_retrieve_platform_docs_memory_english():
    import time

    from app.tools import rag_tools
    rag_tools._FAQ_CACHE = [{"title": "How to login", "content": "click login", "type": "guide"}]
    rag_tools._FAQ_CACHE_LOADED_AT = time.time()
    out = RAGTools.retrieve_platform_docs("login how", 3)
    assert out and out[0]["title"] == "How to login"


def test_search_faq_returns_ranked():
    import time

    from app.tools import rag_tools
    rag_tools._FAQ_CACHE = [{"title": "如何登录", "content": "点右上角登录按钮", "type": "guide"}]
    rag_tools._FAQ_CACHE_LOADED_AT = time.time()
    out = _search_faq("如何登录", 3)
    assert isinstance(out, list)
    assert out[0]["title"]


def test_refresh_faq_cache():
    from app.tools import rag_tools
    rag_tools._FAQ_CACHE = []
    rag_tools._FAQ_CACHE_LOADED_AT = 0.0
    with patch("app.tools.rag_tools._load_faq_cache_from_db", return_value=[{"title": "x", "content": "y", "type": "faq"}]):
        refresh_faq_cache()
    assert rag_tools._FAQ_CACHE and rag_tools._FAQ_CACHE[0]["title"] == "x"


def test_index_document_success():
    chunks = ["第一段", "第二段"]
    with patch("app.tools.chunker.chunk_document", return_value=chunks), \
         patch("app.tools.llm_tools.LLM_tools.embed", return_value=[[0.1] * 384, [0.2] * 384]):
        pool, conn, cursor = _pool_with_cursor()
        with patch("app.tools.rag_tools.get_global_pool", return_value=pool):
            assert RAGTools.index_document("v1", "title", "内容", 1.0) is True
    assert cursor.execute.call_count >= 2  # DELETE + INSERTs
    conn.commit.assert_called_once()


def test_index_document_embedding_failure():
    with patch("app.tools.chunker.chunk_document", return_value=["x"]), \
         patch("app.tools.llm_tools.LLM_tools.embed", return_value=None):
        assert RAGTools.index_document("v1", "title", "内容") is False


def test_index_document_no_chunks():
    with patch("app.tools.chunker.chunk_document", return_value=[]):
        assert RAGTools.index_document("v1", "title", "") is False


def test_index_video_missing_video():
    with patch("app.tools.VideoTools.get_video_info", return_value=None):
        r = RAGTools.index_video("nope")
    assert r["success"] is False


def test_index_video_success():
    from app.models import VideoInfo
    video = VideoInfo(videoId="v1", videoName="标题", tags="a,b", introduction="简介")
    with patch("app.tools.VideoTools.get_video_info", return_value=video), \
         patch("app.tools.chunker.chunk_document", return_value=["c"]), \
         patch("app.tools.llm_tools.LLM_tools.embed", return_value=[[0.1] * 384]):
        pool, conn, cursor = _pool_with_cursor()
        with patch("app.tools.rag_tools.get_global_pool", return_value=pool):
            r = RAGTools.index_video("v1")
    assert r["success"] is True
    assert r["parts"]["title"]["indexed"] is True
    assert r["parts"]["tags"]["indexed"] is True

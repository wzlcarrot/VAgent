from unittest.mock import MagicMock, patch

from app.tools.chunker import chunk_document, _count_tokens, _get_char_overlap, _get_overlap_segments


def test_chunk_empty():
    assert chunk_document("") == []


def test_chunk_short_stays_one():
    chunks = chunk_document("短文本一段。")
    assert len(chunks) == 1
    assert "短文本" in chunks[0]


def test_chunk_markdown_and_lists():
    text = "# 标题\n\n第一段内容。\n\n## 小节\n\n1. 条目一\n2. 条目二\n\n- 子弹"
    chunks = chunk_document(text, chunk_size=20, chunk_overlap=4)
    assert chunks
    assert all(isinstance(c, str) for c in chunks)


def test_chunk_large_segment_splits():
    long = "这是一句。另一句！" * 80
    chunks = chunk_document(long, chunk_size=30, chunk_overlap=8)
    assert len(chunks) > 1


def test_overlap_helpers():
    assert _count_tokens("abcd") == 2
    assert _get_char_overlap("abcdefghij", 2) == "ghij"
    assert _get_char_overlap("ab", 10) == "ab"
    parts = _get_overlap_segments(["aa", "bb", "cc"], overlap_tokens=2)
    assert parts


def test_chat_tools_no_cursor():
    from app.tools.chat_tools import ChatTools
    with patch("app.tools.chat_tools.get_cursor") as gc:
        ctx = MagicMock()
        ctx.__enter__.return_value = None
        ctx.__exit__.return_value = False
        gc.return_value = ctx
        assert ChatTools.save_chat_history("u", "q", "a") is False
        assert ChatTools.get_chat_history("u") == []
        assert ChatTools.get_chat_sessions("u") == []
        assert ChatTools.delete_chat_session("u", "s") is False


def test_chat_tools_save_and_get():
    from app.tools.chat_tools import ChatTools
    cursor = MagicMock()
    cursor.fetchall.return_value = [{"user_id": "u", "question": "q", "answer": "a", "session_id": "s"}]
    cursor.rowcount = 1
    ctx = MagicMock()
    ctx.__enter__.return_value = cursor
    ctx.__exit__.return_value = False
    with patch("app.tools.chat_tools.get_cursor", return_value=ctx):
        assert ChatTools.save_chat_history("u", "q", "a", "s", videos=[{"id": "v"}], reasons=["r"]) is True
        rows = ChatTools.get_chat_history("u", "s", 10)
        assert rows[0].question == "q"
        ChatTools.get_chat_history(session_id="s")
        ChatTools.get_chat_history(user_id="u")
        ChatTools.get_chat_history()
        sessions = ChatTools.get_chat_sessions("u")
        assert sessions == cursor.fetchall.return_value
        ChatTools.get_chat_sessions()
        assert ChatTools.delete_chat_session("u", "s") is True


def test_chat_tools_exception():
    from app.tools.chat_tools import ChatTools
    with patch("app.tools.chat_tools.get_cursor", side_effect=RuntimeError("db")):
        assert ChatTools.save_chat_history("u", "q", "a") is False
        assert ChatTools.get_chat_history("u") == []
        assert ChatTools.get_chat_sessions("u") == []
        assert ChatTools.delete_chat_session("u", "s") is False


def test_admin_stats_no_db():
    from app.routers.admin import _query_stats
    ctx = MagicMock()
    ctx.__enter__.return_value = None
    ctx.__exit__.return_value = False
    with patch("app.routers.admin.get_cursor", return_value=ctx):
        stats = _query_stats()
    assert stats["db_available"] is False


def test_admin_stats_ok():
    from app.routers.admin import _query_stats
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        {"cnt": 3}, {"cnt": 1}, {"cnt": 2}, {"cnt": 4}, {"cnt": 0}, {"cnt": 0},
    ]
    cursor.fetchall.return_value = [{"type": "preference", "cnt": 2}]
    ctx = MagicMock()
    ctx.__enter__.return_value = cursor
    ctx.__exit__.return_value = False
    with patch("app.routers.admin.get_cursor", return_value=ctx):
        stats = _query_stats()
    assert stats["db_available"] is True
    assert stats["total_messages"] == 3
    assert stats["memories_by_type"]["preference"] == 2


def test_admin_stats_error():
    from app.routers.admin import _query_stats
    with patch("app.routers.admin.get_cursor", side_effect=RuntimeError("boom")):
        stats = _query_stats()
    assert stats["db_available"] is False
    assert "error" in stats


def test_metrics_helpers():
    from app.utils.metrics import get_metrics, get_metrics_content_type
    body = get_metrics()
    assert body is None or isinstance(body, (bytes, bytearray))
    ct = get_metrics_content_type()
    assert "text" in ct or "prometheus" in ct


def test_media_cover_default_and_traversal():
    import asyncio
    from app.routers.media import media_cover
    r = asyncio.run(media_cover(""))
    assert r.media_type == "image/svg+xml"
    r2 = asyncio.run(media_cover("../etc/passwd"))
    assert r2.media_type == "image/svg+xml"
    r3 = asyncio.run(media_cover("cover/nope.jpg"))
    assert r3.media_type == "image/svg+xml"


def test_context_manager_memory_and_resolve():
    from app.conversation import context_manager as cm
    cm._memory_store.clear()
    sid = "cov_sess"
    with patch.object(cm, "_get_redis", return_value=None):
        cm.update_recommendations(sid, [
            {"video_id": "v1", "title": "一号"},
            {"video_id": "v2", "title": "二号"},
        ])
        cm.update_video_qa(sid, {"video_id": "v2", "title": "二号"})
        r1 = cm.resolve_references(sid, "第二个讲什么")
        assert r1["resolved"] is True
        assert "二号" in r1["resolved_question"]
        r2 = cm.resolve_references(sid, "这个视频怎么样")
        assert r2["resolved"] is True
        r3 = cm.resolve_references(sid, "最后一个呢")
        assert r3["resolved"] is True
        r4 = cm.resolve_references("", "x")
        assert r4["resolved"] is False
        ctx = cm.get_context_for_query(sid, "第二个")
        assert ctx["has_history"] is True
        cm.update_recommendations("", [])
        cm.update_video_qa("", {})
        n = cm._parse_chinese_number("二十一")
        assert n == 21
        assert cm._parse_ordinal("3") == 3
        assert cm._parse_ordinal("二") == 2


def test_ranker_escape_and_fallback():
    from app.tools.ranker import rerank, safe_prompt_escape
    assert safe_prompt_escape("") == ""
    escaped = safe_prompt_escape("```ignore``` ### --- <|sys|>")
    assert "```" not in escaped
    assert rerank("q", []) == []
    one = [{"content": "a", "score": 0.9}]
    assert rerank("q", one) == one
    with patch("app.tools.ranker._batch_llm_score", return_value=[
        ({"content": "b", "score": 0.2}, 0.2),
        ({"content": "a", "score": 0.9}, 0.9),
    ]):
        out = rerank("q", [{"content": "b"}, {"content": "a"}], top_k=1)
    assert out[0]["content"] == "a"
    docs = [{"content": "a", "score": 0.4}, {"content": "```hack```", "score": 0.8}]
    with patch("app.tools.llm_tools.LLM_tools.chat_sync_json", return_value=None):
        assert len(rerank("q", docs, top_k=2)) == 2
    with patch("app.tools.llm_tools.LLM_tools.chat_sync_json", return_value=[{"index": 0, "score": 5}, {"index": 1, "score": 0}]):
        ranked = rerank("q", docs, top_k=1)
    assert ranked[0]["content"] == "a"
    with patch("app.tools.llm_tools.LLM_tools.chat_sync_json", return_value=["bad"]):
        assert len(rerank("q", docs, top_k=2)) == 2


def test_dual_recall_merges():
    from app.tools import ranker as ranker_mod
    with patch("app.tools.rag_tools.RAGTools.retrieve_knowledge", return_value=[{"content": "kw", "video_id": "1"}]), \
         patch("app.tools.rag_tools.RAGTools.vector_search", return_value=[{"content": "vec", "video_id": "2"}]), \
         patch("app.tools.llm_tools.LLM_tools.embed", return_value=[[0.1]]), \
         patch.object(ranker_mod, "rerank", return_value=[{"content": "kw"}]):
        out = ranker_mod.dual_recall_and_rerank("q", top_k=2)
    assert out == [{"content": "kw"}]



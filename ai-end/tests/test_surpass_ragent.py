"""超越 Ragent 三刀：索引 SLA / citations 时间戳 / 公平排队。"""
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from app.services import video_indexing as vi
from app.tools.rag_tools import RAGTools
from app.tools.video_qa_retrieval import build_citations
from app.utils.chat_stream_permit import (
    _RELEASE_LUA,
    release_stream_permit,
    reset_stream_permits,
    try_acquire_stream_permit,
)


def test_index_stats_pending_alert():
    cursor = MagicMock()
    cursor.fetchone.side_effect = [{"cnt": 20}, {"cnt": 5}, {"cnt": 40}]

    @contextmanager
    def _cursor():
        yield cursor

    with patch.object(vi, "get_cursor", _cursor), \
         patch.object(vi, "list_pending_video_ids", return_value=["v1"] * 12), \
         patch("app.config.settings.index_pending_alert_threshold", 10):
        stats = vi.index_stats()
    assert stats["pending_alert"] is True
    assert stats["videos_pending"] == 12


def test_estimate_chunk_window_introduction():
    start, end = RAGTools._estimate_chunk_window("introduction", 1, 4, 400.0)
    assert start is not None and end is not None
    assert 0 <= start < end <= 400


def test_estimate_chunk_window_title_zero():
    start, end = RAGTools._estimate_chunk_window("title", 0, 1, 120.0)
    assert start == 0.0
    assert end is not None


def test_build_citations_with_start_s():
    docs = [
        {"content": "Python 入门讲解", "score": 0.9, "video_id": "v1",
         "block_type": "introduction_0", "start_s": 12.5, "end_s": 40.0},
    ]
    cites = build_citations(docs)
    assert cites[0]["start_s"] == 12.5
    assert cites[0]["end_s"] == 40.0
    assert cites[0]["video_id"] == "v1"


class TestFairQueueMemory:
    def setup_method(self):
        reset_stream_permits()

    def test_acquire_release_per_user(self):
        with patch("app.config.settings.chat_concurrent_max_global", 2), \
             patch("app.config.settings.chat_concurrent_max_user", 1), \
             patch("app.utils.chat_stream_permit._redis", return_value=None):
            p1 = try_acquire_stream_permit("u1")
            assert p1.acquired
            p2 = try_acquire_stream_permit("u1")
            assert not p2.acquired
            assert p2.queue_position >= 1
            release_stream_permit(p1.token, user_id="u1")
            p3 = try_acquire_stream_permit("u1")
            assert p3.acquired
            # 另一用户不受 u1 释放误伤
            p4 = try_acquire_stream_permit("u2")
            assert p4.acquired


def test_acquire_lua_path_mock():
    """Redis eval 返回 acquired=1 时拿到许可。"""
    mock_r = MagicMock()
    mock_r.eval.return_value = [1, 0, 0]
    with patch("app.config.settings.chat_concurrent_enabled", True), \
         patch("app.utils.chat_stream_permit._redis", return_value=mock_r):
        p = try_acquire_stream_permit("u-lua")
    assert p.acquired
    assert p.token
    mock_r.eval.assert_called()
    script = mock_r.eval.call_args[0][0]
    assert "ZREMRANGEBYSCORE" in script
    assert "ZCARD" in script


def test_release_lua_drops_permit_without_token_key():
    """令牌键过期后仍要按 token 从集合里删掉，不能只在 EXISTS 时才减计数。"""
    assert "ZREM" in _RELEASE_LUA
    assert "EXISTS" not in _RELEASE_LUA


def test_release_lua_keeps_same_user_queue_slot():
    """释放许可不按用户 id 删排队位，同一用户还在等时位置要留着。"""
    assert "qkey" not in _RELEASE_LUA
    assert "ARGV[2]" not in _RELEASE_LUA


def test_acquire_lua_keeps_queue_score_on_retry():
    """同一次排队重试不刷新分数，队首不会因为前端再次请求被排到队尾。"""
    from app.utils.chat_stream_permit import _ACQUIRE_LUA

    assert "ZADD', qkey, 'NX'" in _ACQUIRE_LUA


def test_acquire_lua_queue_path_mock():
    mock_r = MagicMock()
    mock_r.eval.return_value = [0, 3, 3.5]
    mock_r.get.return_value = b"100"
    with patch("app.config.settings.chat_concurrent_enabled", True), \
         patch("app.config.settings.chat_concurrent_max_global", 1), \
         patch("app.utils.chat_stream_permit._redis", return_value=mock_r):
        p = try_acquire_stream_permit("u-lua")
    assert not p.acquired
    assert p.queue_position == 3
    assert p.retry_after_seconds == 3.5

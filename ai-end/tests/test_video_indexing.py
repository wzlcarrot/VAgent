"""video_indexing 服务单测。"""
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from app.services import video_indexing as vi


def test_reindex_pending_empty():
    with patch.object(vi, "list_pending_video_ids", return_value=[]):
        r = vi.reindex_pending(limit=10)
    assert r["indexed_count"] == 0


def test_reindex_pending_success():
    with patch.object(vi, "list_pending_video_ids", side_effect=[["v1", "v2"], []]), \
         patch("app.tools.rag_tools.RAGTools.index_video", return_value={"success": True}):
        r = vi.reindex_pending(limit=10)
    assert r["indexed_count"] == 2


def test_index_stats_no_db():
    @contextmanager
    def _null_cursor():
        yield None

    with patch.object(vi, "get_cursor", _null_cursor):
        stats = vi.index_stats()
    assert stats["db_available"] is False


def test_index_stats_ok():
    cursor = MagicMock()
    cursor.fetchone.side_effect = [{"cnt": 10}, {"cnt": 8}, {"cnt": 40}]
    cursor.fetchall.return_value = [{"video_id": "v9"}]

    @contextmanager
    def _cursor():
        yield cursor

    with patch.object(vi, "get_cursor", _cursor), \
         patch.object(vi, "list_pending_video_ids", return_value=["v9"]):
        stats = vi.index_stats()
    assert stats["db_available"] is True
    assert stats["videos_total"] == 10
    assert stats["videos_pending"] == 1

"""
UserTools 测试：验证 user_action 相关查询的 video_name 通过 LEFT JOIN video_info 获取

背景：user_action 表无 video_name 列，曾直接 SELECT 导致查询永远失败。
修复：LEFT JOIN video_info 取 video_name，本测试防回归。
"""
import pytest
from unittest.mock import patch, MagicMock
from app.tools.user_tools import UserTools


def _mock_cursor_fetchall(rows):
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = rows
    return mock_cursor


class TestRecentLikedVideos:
    @patch("app.tools.user_tools.get_cursor")
    def test_uses_join_with_video_info(self, mock_get):
        """SQL 必须 LEFT JOIN video_info 取 video_name（防回归）"""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_get.return_value.__enter__.return_value = mock_cursor
        UserTools.get_recent_liked_videos("u1")
        sql = mock_cursor.execute.call_args_list[0][0][0]
        assert "LEFT JOIN video_info" in sql
        assert "video_name" in sql
        assert "ua.video_id" in sql

    @patch("app.tools.user_tools.get_cursor")
    def test_returns_video_name_from_join(self, mock_get):
        """返回的 video_name 来自 JOIN 结果"""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"video_id": "v1", "video_name": "Python入门"}]
        mock_cursor.fetchone.return_value = {"count": 1}
        mock_get.return_value.__enter__.return_value = mock_cursor
        result = UserTools.get_recent_liked_videos("u1")
        assert result["videos"] == [{"video_id": "v1", "video_name": "Python入门"}]
        assert result["total"] == 1


class TestRecentFavorites:
    @patch("app.tools.user_tools.get_cursor")
    def test_uses_join(self, mock_get):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_get.return_value.__enter__.return_value = mock_cursor
        UserTools.get_recent_favorites("u1")
        sql = mock_cursor.execute.call_args_list[0][0][0]
        assert "LEFT JOIN video_info" in sql
        assert "action_type = 3" in sql

    @patch("app.tools.user_tools.get_cursor")
    def test_null_video_name_fallback(self, mock_get):
        """video_info 无记录时 video_name 为 None，调用方兜底未知视频"""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"video_id": "v9", "video_name": None}]
        mock_cursor.fetchone.return_value = {"count": 1}
        mock_get.return_value.__enter__.return_value = mock_cursor
        result = UserTools.get_recent_favorites("u1")
        assert result["videos"][0]["video_name"] is None


class TestTopLikedVideos:
    @patch("app.tools.user_tools.get_cursor")
    def test_uses_join_and_group_by(self, mock_get):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"video_id": "v1", "video_name": "热门", "cnt": 3}]
        mock_get.return_value.__enter__.return_value = mock_cursor
        result = UserTools.get_top_liked_videos("u1")
        sql = mock_cursor.execute.call_args_list[0][0][0]
        assert "LEFT JOIN video_info" in sql
        assert "GROUP BY ua.video_id, vi.video_name" in sql
        assert result == [{"video_id": "v1", "video_name": "热门", "count": 3}]


class TestRecentHistory:
    @patch("app.tools.user_tools.get_cursor")
    def test_uses_join_for_video_name(self, mock_get):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"video_id": "v1", "video_name": "历史视频"}]
        mock_cursor.fetchone.return_value = {"count": 2}
        mock_get.return_value.__enter__.return_value = mock_cursor
        result = UserTools.get_recent_history("u1")
        sql = mock_cursor.execute.call_args_list[0][0][0]
        assert "LEFT JOIN video_info" in sql
        assert result["videos"][0]["video_name"] == "历史视频"

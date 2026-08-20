"""记忆召回：ILIKE 转义、负反馈只取 not_helpful。"""
from unittest.mock import MagicMock, patch

from app.tools.memory_tools import MemoryTools


class TestRecallLikeEscape:
    def test_ilike_fallback_escapes_wildcards(self):
        captured = {}

        def _execute(sql, params=None):
            captured["sql"] = sql
            captured["params"] = params
            return None

        cursor = MagicMock()
        cursor.fetchone.return_value = None  # 无 pg_trgm
        cursor.fetchall.return_value = []
        cursor.execute.side_effect = _execute

        ctx = MagicMock()
        ctx.__enter__.return_value = cursor
        ctx.__exit__.return_value = False

        with patch("app.tools.memory_tools.get_cursor", return_value=ctx):
            MemoryTools.recall_memories("u1", query="100%_off", top_k=3)

        assert "ESCAPE" in captured["sql"]
        assert any("100\\%\\_off" in str(p) or "100\\%" in str(p) for p in captured["params"])


class TestNegativeFeedbackIds:
    def test_only_not_helpful_tags(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            {"content": "x", "tags": ["not_helpful", "s1", "video:v_bad"]},
        ]
        ctx = MagicMock()
        ctx.__enter__.return_value = cursor
        ctx.__exit__.return_value = False

        with patch("app.tools.memory_tools.get_cursor", return_value=ctx):
            ids = MemoryTools.get_negative_feedback_video_ids("u1")
        assert ids == ["v_bad"]
        sql = cursor.execute.call_args[0][0]
        assert "ANY(tags)" in sql
        assert cursor.execute.call_args[0][1][1] == "not_helpful"

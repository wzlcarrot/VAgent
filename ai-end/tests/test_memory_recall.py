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

        with patch("app.tools.memory_tools.get_cursor", return_value=ctx), \
             patch("app.config.settings.memory_semantic_recall_enabled", False):
            MemoryTools.recall_memories("u1", query="100%_off", top_k=3)

        # 关键词查询（可能后面还有兜底查询）里应有一条带 ESCAPE 且参数已转义
        calls = cursor.execute.call_args_list
        esc = [c for c in calls if "ESCAPE" in c[0][0]]
        assert esc, "应发出带 ESCAPE 的 ILIKE 查询"
        assert any("100\\%\\_off" in str(p) or "100\\%" in str(p) for p in esc[0][0][1])


class TestNegativeFeedbackIds:
    def test_only_not_helpful_tags(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            {"content": "x", "tags": ["not_helpful", "s1", "video:v_bad"]},
        ]
        ctx = MagicMock()
        ctx.__enter__.return_value = cursor
        ctx.__exit__.return_value = False

        with patch("app.tools.memory_tools.get_cursor", return_value=ctx), \
             patch("app.tools.context_tools._get_redis", return_value=None):
            ids = MemoryTools.get_negative_feedback_video_ids("u1")
        assert ids == ["v_bad"]
        sql = cursor.execute.call_args[0][0]
        assert "ANY(tags)" in sql
        assert cursor.execute.call_args[0][1][1] == "not_helpful"

    def test_merges_redis_cache(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            {"content": "x", "tags": ["not_helpful", "s1", "video:v_db"]},
        ]
        ctx = MagicMock()
        ctx.__enter__.return_value = cursor
        ctx.__exit__.return_value = False
        redis = MagicMock()
        redis.lrange.return_value = [b"v_hot", b"v_db"]

        with patch("app.tools.memory_tools.get_cursor", return_value=ctx), \
             patch("app.tools.context_tools._get_redis", return_value=redis):
            ids = MemoryTools.get_negative_feedback_video_ids("u1")
        assert ids[0] == "v_hot"
        assert "v_db" in ids

    def test_record_negative_feedback_videos(self):
        redis = MagicMock()
        pipe = MagicMock()
        redis.pipeline.return_value = pipe
        with patch("app.tools.context_tools._get_redis", return_value=redis):
            MemoryTools.record_negative_feedback_videos("u1", ["v1", "v2"])
        assert pipe.lpush.call_count == 2
        pipe.execute.assert_called_once()


class TestRecallFallback:
    def test_fallback_when_keyword_miss(self):
        captured = []

        def _execute(sql, params=None):
            captured.append(sql)
            return None

        cursor = MagicMock()
        cursor.fetchone.return_value = None  # 无 pg_trgm → ILIKE 分支
        cursor.fetchall.side_effect = [
            [],  # 关键词查询无命中
            [{"id": 1, "user_id": "u1", "type": "preference", "content": "用户喜欢科幻",
              "source": "inferred", "score": 1.0, "tags": []}],  # 兜底命中
        ]
        cursor.execute.side_effect = _execute
        ctx = MagicMock()
        ctx.__enter__.return_value = cursor
        ctx.__exit__.return_value = False

        with patch("app.tools.memory_tools.get_cursor", return_value=ctx), \
             patch("app.config.settings.memory_recall_fallback", True), \
             patch("app.config.settings.memory_semantic_recall_enabled", False):
            mems = MemoryTools.recall_memories("u1", query="推荐点片子", top_k=3)

        assert len(mems) == 1
        fallback = [s for s in captured if "ILIKE" not in s and "user_memory" in s]
        assert fallback, "关键词无命中时应发出兜底查询"

    def test_no_fallback_when_disabled(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = []
        ctx = MagicMock()
        ctx.__enter__.return_value = cursor
        ctx.__exit__.return_value = False

        with patch("app.tools.memory_tools.get_cursor", return_value=ctx), \
             patch("app.config.settings.memory_recall_fallback", False), \
             patch("app.config.settings.memory_semantic_recall_enabled", False):
            mems = MemoryTools.recall_memories("u1", query="推荐点片子", top_k=3)

        assert mems == []

    def test_no_fallback_when_any_hit(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = [
            {"id": 2, "user_id": "u1", "type": "preference", "content": "用户喜欢科幻",
             "source": "inferred", "score": 1.0, "tags": []},
        ]
        ctx = MagicMock()
        ctx.__enter__.return_value = cursor
        ctx.__exit__.return_value = False

        with patch("app.tools.memory_tools.get_cursor", return_value=ctx), \
             patch("app.config.settings.memory_recall_fallback", True), \
             patch("app.config.settings.memory_semantic_recall_enabled", False):
            mems = MemoryTools.recall_memories("u1", query="科幻", top_k=3)

        assert len(mems) == 1

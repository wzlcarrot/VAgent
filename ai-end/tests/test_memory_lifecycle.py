"""长期记忆治理：冲突取代（supersede）、显式遗忘（retract）、容量淘汰、有效过滤。

借鉴 ragent 的长期记忆设计：无效记忆不物理删除，只打 invalid_at / superseded_by。
"""
from unittest.mock import MagicMock, patch

from app.tools.memory_tools import MemoryTools


def _cursor_ctx(cursor):
    ctx = MagicMock()
    ctx.__enter__.return_value = cursor
    ctx.__exit__.return_value = False
    return ctx


class TestRecallFiltersInvalid:
    def test_recall_sql_excludes_invalid(self):
        captured = {}

        def _execute(sql, params=None):
            captured["sql"] = sql
            return None

        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = []
        cursor.execute.side_effect = _execute

        with patch("app.tools.memory_tools.get_cursor", return_value=_cursor_ctx(cursor)):
            MemoryTools.recall_memories("u1", query="科幻", top_k=3)

        assert "invalid_at IS NULL" in captured["sql"]

    def test_recall_sql_excludes_invalid_without_keywords(self):
        captured = {}

        def _execute(sql, params=None):
            captured["sql"] = sql
            return None

        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.execute.side_effect = _execute

        with patch("app.tools.memory_tools.get_cursor", return_value=_cursor_ctx(cursor)):
            MemoryTools.recall_memories("u1", query="", top_k=5)

        assert "invalid_at IS NULL" in captured["sql"]


class TestSupersede:
    def test_save_supersedes_similar_memory(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"id": 99}  # INSERT ... RETURNING id

        with patch("app.tools.memory_tools.get_cursor", return_value=_cursor_ctx(cursor)), \
             patch.object(MemoryTools, "_find_similar_active", return_value=7):
            ok = MemoryTools.save_memory("u1", "preference", "用户喜欢科幻", source="inferred")

        assert ok is True
        sqls = [c[0][0] for c in cursor.execute.call_args_list]
        supersede = [s for s in sqls if "superseded_by" in s and "invalid_at" in s]
        assert supersede, "应发出软失效 UPDATE"
        # 旧记忆 id=7 被新记忆 id=99 取代
        call = next(c for c in cursor.execute.call_args_list if "superseded_by" in c[0][0])
        params = call[0][1]
        assert 7 in params and 99 in params

    def test_save_without_similar_does_not_supersede(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"id": 100}

        with patch("app.tools.memory_tools.get_cursor", return_value=_cursor_ctx(cursor)), \
             patch.object(MemoryTools, "_find_similar_active", return_value=None):
            ok = MemoryTools.save_memory("u1", "preference", "全新偏好")

        assert ok is True
        sqls = [c[0][0] for c in cursor.execute.call_args_list]
        assert not any("superseded_by" in s for s in sqls)

    def test_save_empty_content_rejected(self):
        assert MemoryTools.save_memory("u1", "preference", "   ") is False
        assert MemoryTools.save_memory("", "preference", "x") is False

    def test_find_similar_active_uses_trgm_threshold(self):
        captured = {}

        def _execute(sql, params=None):
            captured["sql"] = sql
            return None

        cursor = MagicMock()
        cursor.execute.side_effect = _execute
        cursor.fetchone.side_effect = [
            {"x": 1},          # pg_extension 存在
            {"id": 5, "sim": 0.9},  # 相似记忆
        ]
        with patch("app.config.settings.memory_supersede_threshold", 0.6):
            old_id = MemoryTools._find_similar_active(cursor, "u1", "preference", "喜欢科幻")
        assert old_id == 5
        assert "similarity" in captured["sql"]

    def test_find_similar_active_below_threshold_returns_none(self):
        cursor = MagicMock()
        cursor.execute.side_effect = lambda sql, params=None: None
        cursor.fetchone.side_effect = [{"x": 1}, {"id": 5, "sim": 0.1}]
        with patch("app.config.settings.memory_supersede_threshold", 0.6):
            assert MemoryTools._find_similar_active(cursor, "u1", "preference", "无关内容") is None


class TestRetract:
    def test_retract_by_id_soft_invalidates(self):
        cursor = MagicMock()
        cursor.rowcount = 1
        with patch("app.tools.memory_tools.get_cursor", return_value=_cursor_ctx(cursor)):
            n = MemoryTools.retract_memory("u1", memory_id=5)
        assert n == 1
        sql = cursor.execute.call_args[0][0]
        assert "invalid_at = NOW()" in sql and "id = %s" in sql

    def test_retract_by_content(self):
        cursor = MagicMock()
        cursor.rowcount = 2
        with patch("app.tools.memory_tools.get_cursor", return_value=_cursor_ctx(cursor)):
            n = MemoryTools.retract_memory("u1", content="过时偏好")
        assert n == 2
        sql = cursor.execute.call_args[0][0]
        assert "content = %s" in sql

    def test_retract_without_target_noop(self):
        assert MemoryTools.retract_memory("u1") == 0


class TestCapacityEviction:
    def test_evicts_when_over_capacity(self):
        cursor = MagicMock()
        # 第一次 fetchone: INSERT RETURNING id；第二次: COUNT(*) 超限
        cursor.fetchone.side_effect = [{"id": 1}, {"c": 5}]

        with patch("app.tools.memory_tools.get_cursor", return_value=_cursor_ctx(cursor)), \
             patch.object(MemoryTools, "_find_similar_active", return_value=None), \
             patch("app.config.settings.memory_max_per_user", 3):
            MemoryTools.save_memory("u1", "fact", "新事实")

        sqls = [c[0][0] for c in cursor.execute.call_args_list]
        assert any("invalid_at = NOW()" in s and "LIMIT %s" in s for s in sqls), "应触发容量淘汰"

    def test_no_evict_when_under_capacity(self):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [{"id": 1}, {"c": 2}]

        with patch("app.tools.memory_tools.get_cursor", return_value=_cursor_ctx(cursor)), \
             patch.object(MemoryTools, "_find_similar_active", return_value=None), \
             patch("app.config.settings.memory_max_per_user", 3):
            MemoryTools.save_memory("u1", "fact", "新事实")

        sqls = [c[0][0] for c in cursor.execute.call_args_list]
        assert not any("LIMIT %s" in s and "invalid_at = NOW()" in s for s in sqls)


class TestArchive:
    def test_archive_moves_and_deletes(self):
        cursor = MagicMock()
        cursor.rowcount = 3
        with patch("app.tools.memory_tools.get_cursor", return_value=_cursor_ctx(cursor)), \
             patch("app.config.settings.memory_archive_after_days", 30):
            n = MemoryTools.archive_invalid_memories()
        assert n == 3
        sqls = [c[0][0] for c in cursor.execute.call_args_list]
        assert any("INSERT INTO user_memory_archive" in s for s in sqls)
        assert any("DELETE FROM user_memory" in s for s in sqls)
        # 保留天数按参数传入（默认来自 config）
        assert cursor.execute.call_args_list[0][0][1] == (30,)

    def test_archive_explicit_retention_days(self):
        cursor = MagicMock()
        cursor.rowcount = 0
        with patch("app.tools.memory_tools.get_cursor", return_value=_cursor_ctx(cursor)):
            MemoryTools.archive_invalid_memories(retention_days=7)
        assert cursor.execute.call_args_list[0][0][1] == (7,)

    def test_archive_returns_zero_when_no_db(self):
        ctx = MagicMock()
        ctx.__enter__.return_value = None
        ctx.__exit__.return_value = False
        with patch("app.tools.memory_tools.get_cursor", return_value=ctx):
            assert MemoryTools.archive_invalid_memories() == 0

"""记忆合并（二次压缩）测试 —— 多条相似记忆合成更少的概括条目。"""
from unittest.mock import MagicMock, patch

from app.agents.memory_consolidator import consolidate_memories
from app.models import Memory
from app.tools.memory_tools import MemoryTools


class TestConsolidateLlm:
    def test_merges_into_fewer(self):
        items = [
            {"type": "preference", "content": "喜欢科幻"},
            {"type": "preference", "content": "喜欢科幻片"},
            {"type": "preference", "content": "喜欢太空题材"},
        ]
        with patch("app.harness.llm_replay.replay_enabled", return_value=False), \
             patch("app.tools.llm_tools.LLM_tools.chat_sync",
                   return_value='{"items":[{"type":"preference","content":"喜欢科幻与太空题材"}]}'):
            out = consolidate_memories(items)
        assert len(out) == 1
        assert "科幻" in out[0]["content"]

    def test_no_reduction_returns_empty(self):
        items = [{"type": "preference", "content": "a"}, {"type": "preference", "content": "b"}]
        with patch("app.harness.llm_replay.replay_enabled", return_value=False), \
             patch("app.tools.llm_tools.LLM_tools.chat_sync",
                   return_value='{"items":[{"type":"preference","content":"a"},{"type":"preference","content":"b"}]}'):
            assert consolidate_memories(items) == []

    def test_llm_failure_returns_empty(self):
        items = [{"type": "preference", "content": "a"}, {"type": "preference", "content": "b"}]
        with patch("app.harness.llm_replay.replay_enabled", return_value=False), \
             patch("app.tools.llm_tools.LLM_tools.chat_sync", side_effect=RuntimeError("boom")):
            assert consolidate_memories(items) == []

    def test_single_item_noop(self):
        assert consolidate_memories([{"type": "preference", "content": "a"}]) == []

    def test_replay_dedupes(self):
        items = [{"type": "preference", "content": "喜欢科幻"},
                 {"type": "preference", "content": "喜欢科幻"}]
        with patch("app.harness.llm_replay.replay_enabled", return_value=True):
            out = consolidate_memories(items)
        assert len(out) == 1


class TestConsolidateUserMemories:
    def _ctx(self, cursor):
        ctx = MagicMock()
        ctx.__enter__.return_value = cursor
        ctx.__exit__.return_value = False
        return ctx

    def test_merges_softinvalidate_and_insert(self):
        mems = [
            Memory(id=1, user_id="u1", type="preference", content="喜欢科幻"),
            Memory(id=2, user_id="u1", type="preference", content="喜欢科幻片"),
        ]
        cursor = MagicMock()
        with patch.object(MemoryTools, "list_active_memories", return_value=mems), \
             patch("app.agents.memory_consolidator.consolidate_memories",
                   return_value=[{"type": "preference", "content": "喜欢科幻题材"}]), \
             patch("app.tools.memory_tools.get_cursor", return_value=self._ctx(cursor)):
            res = MemoryTools.consolidate_user_memories("u1")
        assert res["consolidated"] == 1
        sqls = [c[0][0] for c in cursor.execute.call_args_list]
        assert any("invalid_at = NOW()" in s for s in sqls)
        assert any("INSERT INTO user_memory" in s for s in sqls)

    def test_too_few_items_noop(self):
        with patch.object(MemoryTools, "list_active_memories",
                          return_value=[Memory(id=1, user_id="u1", type="preference", content="a")]):
            res = MemoryTools.consolidate_user_memories("u1")
        assert res["consolidated"] == 0

    def test_no_merge_result_keeps_originals(self):
        mems = [
            Memory(id=1, user_id="u1", type="preference", content="a"),
            Memory(id=2, user_id="u1", type="preference", content="b"),
        ]
        cursor = MagicMock()
        with patch.object(MemoryTools, "list_active_memories", return_value=mems), \
             patch("app.agents.memory_consolidator.consolidate_memories", return_value=[]), \
             patch("app.tools.memory_tools.get_cursor", return_value=self._ctx(cursor)):
            res = MemoryTools.consolidate_user_memories("u1")
        assert res["consolidated"] == 0
        # 没有合并结果 → 不发失效/写入（只可能有一条统计 COUNT）
        sqls = [c[0][0] for c in cursor.execute.call_args_list]
        assert not any("invalid_at = NOW()" in s for s in sqls)
        assert not any("INSERT INTO user_memory" in s for s in sqls)


    def test_loops_until_reaches_target(self):
        """合并不止一轮：降回阈值才停，而不是只合一次。"""
        mems = [
            Memory(id=1, user_id="u1", type="preference", content="a"),
            Memory(id=2, user_id="u1", type="preference", content="b"),
        ]
        cursor = MagicMock()
        with patch.object(MemoryTools, "list_active_memories", return_value=mems), \
             patch.object(MemoryTools, "active_memory_count", side_effect=[45, 45, 20, 20]), \
             patch("app.agents.memory_consolidator.consolidate_memories",
                   return_value=[{"type": "preference", "content": "m"}]), \
             patch("app.tools.memory_tools.get_cursor", return_value=self._ctx(cursor)):
            res = MemoryTools.consolidate_user_memories("u1")
        assert res["consolidated"] == 2  # 两轮各合 1 条

    def test_stops_when_no_progress(self):
        """合不动（无进展）就停，不会死循环。"""
        mems = [
            Memory(id=1, user_id="u1", type="preference", content="a"),
            Memory(id=2, user_id="u1", type="preference", content="b"),
        ]
        with patch.object(MemoryTools, "list_active_memories", return_value=mems), \
             patch.object(MemoryTools, "active_memory_count", return_value=45), \
             patch("app.agents.memory_consolidator.consolidate_memories", return_value=[]):
            res = MemoryTools.consolidate_user_memories("u1")
        assert res["consolidated"] == 0

"""记忆冲突判定（LLM Judge）测试。"""
from unittest.mock import patch

from app.agents.memory_judge import _parse, judge_memory


class TestParse:
    def test_valid_actions(self):
        assert _parse('{"action":"ADD","target_id":null}').action == "ADD"
        d = _parse('{"action":"SUPERSEDE","target_id":3}')
        assert d.action == "SUPERSEDE" and d.target_id == 3
        assert _parse('{"action":"NOOP"}').action == "NOOP"

    def test_tolerates_noise(self):
        d = _parse('好的：{"action":"SUPERSEDE","target_id":7} 以上')
        assert d and d.target_id == 7

    def test_invalid(self):
        assert _parse("不是 JSON") is None
        assert _parse('{"action":"UNKNOWN"}') is None
        # SUPERSEDE 缺 target 视为无效
        assert _parse('{"action":"SUPERSEDE"}') is None


class TestJudgeReplay:
    def test_replay_exact_duplicate_supersedes(self):
        with patch("app.harness.llm_replay.replay_enabled", return_value=True), \
             patch("app.config.settings.memory_judge_enabled", True):
            d = judge_memory("用户喜欢科幻", [{"id": 1, "content": "用户喜欢科幻"}])
        assert d.action == "SUPERSEDE" and d.target_id == 1
        assert d.source == "replay"

    def test_replay_distinct_adds(self):
        with patch("app.harness.llm_replay.replay_enabled", return_value=True):
            d = judge_memory("用户喜欢茶", [{"id": 1, "content": "用户在学吉他"}])
        assert d.action == "ADD"


class TestJudgeLlm:
    def test_llm_supersede(self):
        with patch("app.harness.llm_replay.replay_enabled", return_value=False), \
             patch("app.tools.llm_tools.LLM_tools.chat_sync",
                   return_value='{"action":"SUPERSEDE","target_id":5}'):
            d = judge_memory("用户偏爱科幻片", [{"id": 5, "content": "用户喜欢科幻电影"}])
        assert d.action == "SUPERSEDE" and d.target_id == 5 and d.source == "llm"

    def test_llm_failure_failsafe_to_add(self):
        with patch("app.harness.llm_replay.replay_enabled", return_value=False), \
             patch("app.tools.llm_tools.LLM_tools.chat_sync", side_effect=RuntimeError("boom")):
            d = judge_memory("新偏好", [{"id": 1, "content": "旧偏好"}])
        assert d.action == "ADD" and d.source == "fallback"

    def test_empty_content_noop(self):
        assert judge_memory("", [{"id": 1, "content": "x"}]).action == "NOOP"


class TestSaveWithSupersedeId:
    def test_supersede_id_skips_similarity_lookup(self):
        from unittest.mock import MagicMock

        from app.tools.memory_tools import MemoryTools

        cursor = MagicMock()
        cursor.fetchone.return_value = {"id": 88}
        ctx = MagicMock()
        ctx.__enter__.return_value = cursor
        ctx.__exit__.return_value = False

        with patch("app.tools.memory_tools.get_cursor", return_value=ctx), \
             patch.object(MemoryTools, "_find_similar_active") as mock_find:
            ok = MemoryTools.save_memory(
                "u1", "preference", "用户偏爱科幻片", supersede_id=5,
            )
        assert ok is True
        mock_find.assert_not_called()  # 直接指定目标，不再做相似度查找
        call = next(c for c in cursor.execute.call_args_list if "superseded_by" in c[0][0])
        assert 5 in call[0][1] and 88 in call[0][1]

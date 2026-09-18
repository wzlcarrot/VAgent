"""记忆提取攒批（pending 阈值）测试 —— 借鉴 ragent 的成本优化。"""
from unittest.mock import patch

import app.routers.chat_pipeline as cp


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def rpush(self, key, value):
        self.store.setdefault(key, []).append(value)

    def expire(self, key, ttl):
        pass

    def llen(self, key):
        return len(self.store.get(key, []))

    def lrange(self, key, start, end):
        return list(self.store.get(key, []))

    def delete(self, key):
        self.store.pop(key, None)


def test_batches_until_threshold():
    fake = _FakeRedis()
    calls = []
    with patch("app.tools.context_tools._get_redis", return_value=fake), \
         patch.object(cp, "extract_memories_from_turns",
                      side_effect=lambda u, t, s: calls.append(list(t))), \
         patch("app.config.settings.memory_extract_min_turns", 3):
        cp.maybe_extract_memories_from_conversation("u1", "q1", "a1", "s1")
        cp.maybe_extract_memories_from_conversation("u1", "q2", "a2", "s1")
        assert calls == []  # 未达阈值，不调 LLM
        cp.maybe_extract_memories_from_conversation("u1", "q3", "a3", "s1")
    assert len(calls) == 1
    assert [t["q"] for t in calls[0]] == ["q1", "q2", "q3"]  # 批量提取，不丢信息
    assert fake.store.get("vagent:mem_pending:s1") is None  # 提取后清空


def test_threshold_one_extracts_each_turn():
    calls = []
    with patch("app.tools.context_tools._get_redis", return_value=_FakeRedis()), \
         patch.object(cp, "extract_memories_from_turns",
                      side_effect=lambda u, t, s: calls.append(list(t))), \
         patch("app.config.settings.memory_extract_min_turns", 1):
        cp.maybe_extract_memories_from_conversation("u1", "q", "a", "s1")
    assert len(calls) == 1


def test_fallback_when_redis_unavailable():
    calls = []
    with patch("app.tools.context_tools._get_redis", return_value=None), \
         patch.object(cp, "extract_memories_from_turns",
                      side_effect=lambda u, t, s: calls.append(list(t))), \
         patch("app.config.settings.memory_extract_min_turns", 3):
        cp.maybe_extract_memories_from_conversation("u1", "q", "a", "s1")
    assert len(calls) == 1  # Redis 挂了 → 退化为逐轮


def test_empty_inputs_noop():
    assert cp.maybe_extract_memories_from_conversation("", "q", "a") is None
    assert cp.maybe_extract_memories_from_conversation("u1", "q", "") is None


def test_extract_turns_filters_empty_answer():
    with patch("app.tools.llm_tools.LLM_tools.chat_sync_typed") as mock_llm:
        cp.extract_memories_from_turns("u1", [{"q": "q", "a": ""}])
    mock_llm.assert_not_called()

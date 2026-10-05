"""LLM Replay + 限流测试。"""
import os
from unittest.mock import patch

import pytest

from app.agents.workflows.constants import WorkflowType
from app.harness.llm_replay import (
    match_response,
    replay_chat,
    replay_chat_with_tools,
    replay_grounding_check,
    replay_stream_chat,
)
from app.routers.chat_rate_limit import chat_rate_limited, reset_chat_rate_limit


class TestLlmReplay:
    def test_match_response_by_keyword(self):
        fixture = {
            "responses": [{"match_keywords": ["注册"], "content": "去首页注册"}],
            "default_response": "default",
        }
        out = match_response([{"role": "user", "content": "怎么注册账号"}], fixture)
        assert out == "去首页注册"

    def test_demo_mode_enables_replay(self):
        with patch("app.config.settings.demo_mode", True), \
             patch("app.config.settings.llm_replay_enabled", False), \
             patch("app.config.settings.deepseek_api_key", ""):
            from app.harness.llm_replay import replay_enabled
            assert replay_enabled() is True

    def test_demo_mode_with_api_key_uses_live_llm(self):
        with patch("app.config.settings.demo_mode", True), \
             patch("app.config.settings.llm_replay_enabled", False), \
             patch("app.config.settings.deepseek_api_key", "sk-live"):
            from app.harness.llm_replay import replay_enabled
            assert replay_enabled() is False

    def test_replay_chat_when_enabled(self):
        with patch.dict(os.environ, {"VAGENT_LLM_REPLAY": "1"}):
            with patch("app.harness.llm_replay.replay_enabled", return_value=True):
                with patch("app.harness.llm_replay.load_fixture") as mock_load:
                    mock_load.return_value = {
                        "default_response": "replay ok",
                        "responses": [],
                    }
                    out = replay_chat([{"role": "user", "content": "hi"}], "default")
                    assert out == "replay ok"

    def test_replay_chat_with_tools_router(self):
        with patch("app.harness.llm_replay.replay_enabled", return_value=True):
            out = replay_chat_with_tools(
                [{"role": "user", "content": "推荐一些科技视频"}],
                tools=[],
            )
        assert out is not None
        assert out["arguments"]["intent_type"] == WorkflowType.RECOMMEND

    @pytest.mark.asyncio
    async def test_replay_stream_chat_chunks(self):
        with patch("app.harness.llm_replay.replay_enabled", return_value=True):
            with patch("app.harness.llm_replay.replay_chat", return_value="演示流式回复"):
                chunks = []
                async for c in replay_stream_chat([{"role": "user", "content": "hi"}]):
                    chunks.append(c)
        assert "".join(chunks) == "演示流式回复"

    def test_replay_grounding_check(self):
        with patch("app.harness.llm_replay.replay_enabled", return_value=True):
            ok = replay_grounding_check("Python 入门语法[1]", "Python 入门语法讲解")
            assert ok is True

    def test_replay_video_qa_react_tools(self):
        with patch("app.harness.llm_replay.replay_enabled", return_value=True):
            tools = [{"type": "function", "function": {"name": "search_video_chunks"}}]
            out = replay_chat_with_tools(
                [{"role": "user", "content": "用户问题: 讲了什么"}],
                tools=tools,
            )
        assert out is not None
        assert out["tool_name"] == "search_video_chunks"


class TestChatRateLimit:
    _UID = "rate-test-user"

    def setup_method(self):
        # 必须带 user_id：否则 reset_chat_rate_limit() 只清内存、不清 Redis，
        # 限流计数会跨测试/跨次运行残留，导致本测试假失败。
        reset_chat_rate_limit(self._UID)

    def teardown_method(self):
        reset_chat_rate_limit(self._UID)

    def test_rate_limit_blocks_after_threshold(self):
        uid = self._UID
        for _ in range(30):
            assert chat_rate_limited(uid) is False
        assert chat_rate_limited(uid) is True

    def test_rate_limit_does_not_refresh_window_on_each_hit(self):
        class _Redis:
            def __init__(self):
                self.counts = {}
                self.ttls = {}
                self.expire_calls = 0

            def incr(self, key):
                self.counts[key] = self.counts.get(key, 0) + 1
                return self.counts[key]

            def expire(self, key, seconds):
                self.expire_calls += 1
                self.ttls[key] = seconds
                return True

            def ttl(self, key):
                return self.ttls.get(key, -1)

            def delete(self, key):
                self.counts.pop(key, None)
                self.ttls.pop(key, None)

        fake = _Redis()
        uid = "ttl-window-user"
        with patch("app.routers.chat_rate_limit._redis", return_value=fake):
            for _ in range(31):
                chat_rate_limited(uid)
            assert fake.expire_calls == 1
            assert chat_rate_limited(uid) is True
            assert fake.expire_calls == 1

"""
compact_service 单元测试：覆盖 Microcompact 预处理、compact 边界/摘要标记、兜底摘要。

这些是纯逻辑函数（不依赖 Redis/LLM），是 context 压缩的核心防线。
"""
import asyncio

from app.tools.compact_service import (
    COMPACT_PROMPT_TEMPLATE,
    _fallback_summary,
    compact_conversation,
    create_compact_boundary,
    create_compact_summary,
    is_compact_boundary,
    is_compact_summary,
    microcompact_messages,
)


class TestMicrocompact:
    def test_empty_returns_empty(self):
        assert microcompact_messages([]) == ([], 0)

    def test_removes_empty_assistant_and_system(self):
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": ""},
            {"role": "system", "content": ""},
            {"role": "user", "content": "again"},
        ]
        result, saved = microcompact_messages(msgs)
        # 移除 2 条空消息，剩余 [user, user] 再合并 1 条 → 共省 3 条
        assert saved == 3
        assert len(result) == 1
        assert result[0]["content"] == "hi\nagain"

    def test_merges_consecutive_same_role(self):
        msgs = [
            {"role": "user", "content": "第一问"},
            {"role": "user", "content": "第二问"},
            {"role": "assistant", "content": "回答"},
            {"role": "user", "content": "第三问"},
        ]
        result, saved = microcompact_messages(msgs)
        assert saved == 1
        assert result[0]["content"] == "第一问\n第二问"
        assert result[1]["content"] == "回答"
        assert result[2]["content"] == "第三问"

    def test_does_not_merge_str_and_list_content(self):
        msgs = [
            {"role": "user", "content": "看图"},
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "x"}}]},
        ]
        result, _ = microcompact_messages(msgs)
        assert len(result) == 2  # 多模态不合并，避免破坏结构

    def test_keeps_empty_user_content(self):
        msgs = [{"role": "user", "content": ""}]
        result, saved = microcompact_messages(msgs)
        assert saved == 0
        assert len(result) == 1


class TestCompactBoundary:
    def test_create_boundary_is_internal(self):
        b = create_compact_boundary()
        assert b["is_internal"] is True
        assert b["role"] == "system"
        assert "auto" in b["content"]

    def test_is_compact_boundary_detects_internal(self):
        assert is_compact_boundary(create_compact_boundary()) is True
        assert is_compact_boundary({"role": "user", "content": "普通消息"}) is False

    def test_create_summary_is_internal(self):
        s = create_compact_summary("摘要内容")
        assert s["is_internal"] is True
        assert s["content"] == "摘要内容"

    def test_is_compact_summary_detects_internal(self):
        assert is_compact_summary(create_compact_summary("x")) is True
        assert is_compact_summary({"role": "user", "content": "普通"}) is False


class TestFallbackSummary:
    def test_creates_summary_text(self):
        msgs = [
            {"role": "user", "content": "这个视频讲了什么"},
            {"role": "assistant", "content": "讲了注意力机制"},
            {"role": "user", "content": "还有呢"},
        ]
        text = _fallback_summary(msgs)
        assert "对话共 3 条" in text
        assert "用户主要询问" in text
        assert "助手已回复：1 轮" in text

    def test_truncates_long_content(self):
        msgs = [{"role": "user", "content": "x" * 500}]
        text = _fallback_summary(msgs)
        assert len(text) < 400

    def test_empty_messages(self):
        assert _fallback_summary([]).startswith("对话共 0 条")


class TestCompactConversation:
    def test_redis_unavailable_returns_failure(self):
        from unittest.mock import patch

        async def _run():
            with patch("app.tools.context_tools._get_redis", return_value=None):
                return await compact_conversation("s1")

        result = asyncio.run(_run())
        assert result["success"] is False
        assert "Redis" in result["reason"]

    def test_too_few_messages_returns_failure(self):
        from unittest.mock import MagicMock, patch

        client = MagicMock()
        client.lrange.return_value = ["{}", "{}"]  # 少于 4 条

        async def _run():
            with patch("app.tools.context_tools._get_redis", return_value=client):
                return await compact_conversation("s1")

        result = asyncio.run(_run())
        assert result["success"] is False
        assert "消息太少" in result["reason"]

    def test_prompt_template_contains_history_placeholder(self):
        assert "{history}" in COMPACT_PROMPT_TEMPLATE

    def test_existing_boundary_returns_failure(self):
        import json as json_mod
        from unittest.mock import MagicMock, patch

        client = MagicMock()
        boundary = create_compact_boundary()
        # 14 条消息 → recent_count=10，old_messages=4，其中含 boundary
        msgs = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"内容{i}"} for i in range(12)]
        msgs.insert(2, boundary)  # 把 boundary 塞进 old 区
        raw = [json_mod.dumps(m) for m in msgs]
        client.lrange.return_value = raw

        async def _run():
            with patch("app.tools.context_tools._get_redis", return_value=client):
                return await compact_conversation("s1")

        result = asyncio.run(_run())
        assert result["success"] is False
        assert "已有压缩边界" in result["reason"]

    def test_success_path_with_llm_summary(self):
        import json as json_mod
        from unittest.mock import MagicMock, patch

        client = MagicMock()
        # 12 条消息，context_max_rounds=5 → recent_count=10，old_messages=2
        raw = [json_mod.dumps({"role": "user" if i % 2 == 0 else "assistant", "content": f"内容{i}"}) for i in range(12)]
        client.lrange.return_value = raw

        async def _run():
            with patch("app.tools.context_tools._get_redis", return_value=client), \
                 patch("app.tools.llm_tools.LLM_tools.chat_sync_with_usage", return_value=("压缩后的摘要", {"completion_tokens": 10})):
                return await compact_conversation("s1")

        result = asyncio.run(_run())
        assert result["success"] is True
        assert result["summary_length"] == len("压缩后的摘要")
        # 写回 Redis：delete + 多次 rpush + expire
        assert client.pipeline.called or client.delete.called

    def test_fallback_summary_when_llm_fails(self):
        import json as json_mod
        from unittest.mock import MagicMock, patch

        client = MagicMock()
        raw = [json_mod.dumps({"role": "user" if i % 2 == 0 else "assistant", "content": f"内容{i}"}) for i in range(12)]
        client.lrange.return_value = raw

        async def _run():
            with patch("app.tools.context_tools._get_redis", return_value=client), \
                 patch("app.tools.llm_tools.LLM_tools.chat_sync_with_usage", side_effect=Exception("LLM down")):
                return await compact_conversation("s1")

        result = asyncio.run(_run())
        assert result["success"] is True
        # LLM 失败时用 _fallback_summary 兜底，摘要非空
        assert result["summary_length"] > 0

"""
分层 token 估算 + 消息模型 dataclass 测试

覆盖：
- token_estimation：精估/粗估/role 开销/多模态块权重
- message_models：Message 序列化 + is_internal 兼容式识别（新字段 + 旧字符串 flag）
- compact_service：boundary/summary 生成、microcompact 合并、向后兼容
"""
from app.tools import compact_service
from app.tools.message_models import Message


class TestTokenEstimation:
    def test_count_tokens_empty(self):
        from app.tools.token_estimation import count_tokens
        assert count_tokens("") == 0

    def test_count_tokens_chinese(self):
        """中文约 0.7 token/char（无 tiktoken 时走 rough）"""
        from app.tools.token_estimation import rough_token_count
        assert rough_token_count("你好世界") >= 1

    def test_rough_token_count_monotonic(self):
        """更长的文本粗估 token 不递减"""
        from app.tools.token_estimation import rough_token_count
        assert rough_token_count("a" * 100) >= rough_token_count("a" * 10)

    def test_count_messages_tokens_role_overhead(self):
        """每条消息计 role 开销（+4），纯文本按内容估算"""
        from app.tools.token_estimation import count_messages_tokens
        msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        total = count_messages_tokens(msgs)
        assert total >= 8  # 2 条 × 4 role 开销

    def test_count_messages_image_block_weight(self):
        """多模态块：image 按固定权重计费"""
        from app.tools.token_estimation import IMAGE_BLOCK_TOKENS, count_messages_tokens
        msgs = [{"role": "user", "content": [{"type": "image"}]}]
        total = count_messages_tokens(msgs)
        assert total >= 4 + IMAGE_BLOCK_TOKENS

    def test_count_messages_accepts_message_object(self):
        """count_messages_tokens 兼容 Message dataclass 输入"""
        from app.tools.token_estimation import count_messages_tokens
        m = Message(role="user", content="你好")
        assert count_messages_tokens([m]) >= 4


class TestMessageModel:
    def test_to_dict_roundtrip(self):
        m = Message(role="user", content="你好", is_internal=False)
        d = m.to_dict()
        assert d["role"] == "user"
        assert d["content"] == "你好"
        assert "is_internal" not in d  # 非内部消息不写该字段

        m2 = Message.from_dict(d)
        assert m2.role == "user"
        assert m2.content == "你好"
        assert m2.is_internal is False

    def test_to_dict_internal(self):
        m = Message(role="system", content="trigger=auto", is_internal=True)
        d = m.to_dict()
        assert d["is_internal"] is True

    def test_json_roundtrip(self):
        m = Message(role="assistant", content="回答：中文", timestamp="2026-01-01")
        m2 = Message.from_json(m.to_json())
        assert m2.content == "回答：中文"
        assert m2.role == "assistant"

    def test_from_json_invalid_fallback(self):
        m = Message.from_json("not json{{{")
        assert m.role == "unknown"
        assert m.content == ""

    def test_is_internal_recognition(self):
        """新格式：is_internal 字段识别 boundary/summary"""
        boundary = Message(role="system", content="trigger=auto", is_internal=True)
        assert boundary.is_compact_boundary is True
        assert boundary.is_compact_summary is True

    def test_legacy_string_flag_recognition(self):
        """旧格式：字符串 flag 仍可识别（兼容存量 Redis 数据）"""
        legacy = Message(role="system", content="[__compact_summary__]\n历史摘要", is_internal=False)
        assert legacy.is_compact_summary is True
        assert legacy.is_compact_boundary is False


class TestCompactCompatibility:
    def test_create_compact_boundary_structured(self):
        """新 boundary 用 is_internal 字段，不再拼接字符串 flag"""
        b = compact_service.create_compact_boundary()
        assert b["role"] == "system"
        assert b.get("is_internal") is True
        assert "__compact_boundary__" not in b.get("content", "")

    def test_is_compact_boundary_dual_path(self):
        """is_compact_boundary 兼容新字段 + 旧字符串 flag"""
        assert compact_service.is_compact_boundary({"role": "system", "content": "x", "is_internal": True})
        assert compact_service.is_compact_boundary(
            {"role": "system", "content": "[__compact_boundary__] trigger=auto"})
        assert not compact_service.is_compact_boundary({"role": "user", "content": "正常消息"})

    def test_is_compact_summary_dual_path(self):
        assert compact_service.is_compact_summary({"role": "system", "content": "摘要", "is_internal": True})
        assert compact_service.is_compact_summary({"role": "system", "content": "[__compact_summary__]\n摘要"})

    def test_microcompact_merges_same_role(self):
        """microcompact 合并连续同角色消息，且不破坏多模态块"""
        msgs = [
            {"role": "user", "content": "第一句"},
            {"role": "user", "content": "第二句"},
            {"role": "assistant", "content": ""},  # 空 assistant 被清理
            {"role": "assistant", "content": "回答"},
        ]
        merged, saved = compact_service.microcompact_messages(msgs)
        assert saved >= 1  # 空 assistant 被清理 + user 合并
        # 两个 user 应合并为一条
        user_msgs = [m for m in merged if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert "第一句\n第二句" in user_msgs[0]["content"]

    def test_microcompact_keeps_multimodal_blocks(self):
        """list content（多模态）不合并，避免破坏结构"""
        msgs = [
            {"role": "user", "content": "文字"},
            {"role": "user", "content": [{"type": "image"}]},
        ]
        merged, _ = compact_service.microcompact_messages(msgs)
        assert len(merged) == 2

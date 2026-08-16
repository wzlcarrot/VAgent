"""
LLM chat_sync_with_usage 测试：返回 (content, usage)，供 compact 精确计数
"""
from unittest.mock import MagicMock, patch


class TestChatSyncWithUsage:
    def test_returns_content_and_usage(self):
        from app.tools.llm_tools import LLM_tools
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "压缩摘要"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 42, "total_tokens": 142},
        }
        mock_client.post.return_value = mock_resp

        with patch("app.tools.llm_tools._get_sync_client", return_value=mock_client):
            result = LLM_tools.chat_sync_with_usage([{"role": "user", "content": "hi"}])

        assert result is not None
        content, usage = result
        assert content == "压缩摘要"
        assert usage["completion_tokens"] == 42
        assert usage["total_tokens"] == 142

    def test_failure_returns_none(self):
        from app.tools.llm_tools import LLM_tools
        mock_client = MagicMock()
        mock_client.post.side_effect = Exception("network down")
        with patch("app.tools.llm_tools._get_sync_client", return_value=mock_client):
            result = LLM_tools.chat_sync_with_usage([{"role": "user", "content": "hi"}])
        assert result is None

    def test_provider_delegation(self):
        """带 provider 参数走 provider 工厂解析"""
        from app.tools.llm_tools import LLM_tools
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "x"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        mock_client.post.return_value = mock_resp
        with patch("app.tools.llm_tools._get_sync_client", return_value=mock_client):
            result = LLM_tools.chat_sync_with_usage([{"role": "user", "content": "hi"}], provider="deepseek")
        assert result is not None

"""P1 商业化：并发许可 / LLM retry SSE / Token 预算。"""
import queue
from unittest.mock import patch

import pytest

from app.harness.llm_progress import emit_llm_retry, reset_llm_progress_queue, set_llm_progress_queue
from app.streaming.event_bridge import retry_event
from app.utils.chat_stream_permit import (
    release_stream_permit,
    reset_stream_permits,
    try_acquire_stream_permit,
)


class TestStreamPermit:
    def setup_method(self):
        reset_stream_permits()

    def test_acquire_and_release_memory(self):
        with patch("app.config.settings.chat_concurrent_max_global", 2), \
             patch("app.config.settings.chat_concurrent_max_user", 2), \
             patch("app.utils.chat_stream_permit._redis", return_value=None):
            p1 = try_acquire_stream_permit("u1")
            p2 = try_acquire_stream_permit("u1")
            assert p1.acquired and p2.acquired
            p3 = try_acquire_stream_permit("u1")
            assert not p3.acquired
            assert p3.queue_position >= 1
            assert p3.retry_after_seconds > 0
            release_stream_permit(p1.token)
            p4 = try_acquire_stream_permit("u1")
            assert p4.acquired

    def test_disabled_always_acquired(self):
        with patch("app.config.settings.chat_concurrent_enabled", False):
            p = try_acquire_stream_permit("u1")
            assert p.acquired


class TestRetryEvent:
    def test_retry_event_shape(self):
        evt = retry_event("LLM.chat_sync", next_attempt=2, max_attempts=3, wait_s=1.5, status_code=429)
        assert evt["type"] == "retry"
        assert evt["op"] == "LLM.chat_sync"
        assert evt["next_attempt"] == 2
        assert evt["status_code"] == 429

    def test_emit_llm_retry_queue(self):
        q: queue.Queue = queue.Queue()
        token = set_llm_progress_queue(q)
        try:
            emit_llm_retry("LLM.chat_sync", next_attempt=2, max_attempts=3, wait_s=2.0, status_code=503)
            evt = q.get_nowait()
            assert evt["type"] == "retry"
            assert evt["wait_s"] == 2.0
        finally:
            reset_llm_progress_queue(token)


class TestContextBudgetValidation:
    def test_compact_threshold_positive(self):
        from app.config import validate_rag_config
        with patch("app.config.settings.compact_token_threshold", 0):
            with pytest.raises(ValueError, match="compact_token_threshold"):
                validate_rag_config()

    def test_concurrent_limits_monotonic(self):
        from app.config import validate_rag_config
        with patch("app.config.settings.chat_concurrent_max_global", 1), \
             patch("app.config.settings.chat_concurrent_max_user", 5):
            with pytest.raises(ValueError, match="chat_concurrent_max_global"):
                validate_rag_config()

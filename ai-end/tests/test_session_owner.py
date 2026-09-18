"""会话归属校验：防止用他人 session_id 读/写短期记忆（越权）。"""
from unittest.mock import patch

from app.tools.context_tools import ensure_session_owner


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    def get(self, key):
        return self.store.get(key)


def test_first_user_claims_session():
    fake = _FakeRedis()
    with patch("app.tools.context_tools._get_redis", return_value=fake):
        assert ensure_session_owner("user_a", "s1") is True


def test_same_user_can_reuse():
    fake = _FakeRedis()
    with patch("app.tools.context_tools._get_redis", return_value=fake):
        assert ensure_session_owner("user_a", "s1") is True
        assert ensure_session_owner("user_a", "s1") is True


def test_other_user_rejected():
    fake = _FakeRedis()
    with patch("app.tools.context_tools._get_redis", return_value=fake):
        ensure_session_owner("user_a", "s1")
        assert ensure_session_owner("user_b", "s1") is False


def test_different_sessions_independent():
    fake = _FakeRedis()
    with patch("app.tools.context_tools._get_redis", return_value=fake):
        assert ensure_session_owner("user_a", "s1") is True
        assert ensure_session_owner("user_b", "s2") is True


def test_redis_unavailable_degrades_open():
    with patch("app.tools.context_tools._get_redis", return_value=None):
        assert ensure_session_owner("user_a", "s1") is True


def test_empty_inputs_rejected():
    assert ensure_session_owner("", "s1") is False
    assert ensure_session_owner("user_a", "") is False

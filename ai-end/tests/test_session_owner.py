"""会话归属校验：防止用他人 session_id 读/写短期记忆（越权）。"""
from unittest.mock import patch

from app.tools.context_tools import ensure_session_owner


class _FakeRedis:
    def __init__(self):
        self.store = {}
        self.expires = []

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    def get(self, key):
        return self.store.get(key)

    def delete(self, *keys):
        removed = 0
        for key in keys:
            if key in self.store:
                del self.store[key]
                removed += 1
        return removed

    def expire(self, key, ttl):
        self.expires.append((key, ttl))
        return True

    def sadd(self, key, *members):
        bucket = self.store.setdefault(key, set())
        if not isinstance(bucket, set):
            bucket = set()
            self.store[key] = bucket
        bucket.update(members)
        return len(members)

    def sismember(self, key, member):
        bucket = self.store.get(key, set())
        return member in bucket if isinstance(bucket, set) else False


def test_first_user_claims_session():
    fake = _FakeRedis()
    with patch("app.tools.context_tools._get_redis", return_value=fake):
        assert ensure_session_owner("user_a", "s1") is True


def test_same_user_can_reuse():
    fake = _FakeRedis()
    with patch("app.tools.context_tools._get_redis", return_value=fake):
        assert ensure_session_owner("user_a", "s1") is True
        assert ensure_session_owner("user_a", "s1") is True
        assert len(fake.expires) == 1
        assert fake.expires[0][1] > 0


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


def test_redis_unavailable_fails_closed():
    """Redis 不可用时拒绝（fail-closed）：鉴权决策不能在依赖故障时放行。"""
    with patch("app.tools.context_tools._get_redis", return_value=None):
        try:
            ensure_session_owner("user_a", "s1")
            raise AssertionError("should have raised RuntimeError")
        except RuntimeError:
            pass


def test_redis_error_fails_closed():
    """Redis 调用异常时同样 fail-closed。"""
    with patch("app.tools.context_tools._get_redis", side_effect=Exception("boom")):
        try:
            ensure_session_owner("user_a", "s1")
            raise AssertionError("should have raised RuntimeError")
        except RuntimeError:
            pass


def test_clear_session_memory_drops_messages_summary_and_owner():
    from app.tools.context_tools import clear_session_memory

    fake = _FakeRedis()
    fake.store["session:s1:messages"] = "[]"
    fake.store["session:s1:summary"] = "old"
    fake.store["session:s1:owner"] = "user_a"
    fake.store["session:s1:last_compact"] = "1"
    fake.store["session:s2:messages"] = "keep"
    with patch("app.tools.context_tools._get_redis", return_value=fake):
        clear_session_memory("s1")
    assert "session:s1:messages" not in fake.store
    assert "session:s1:summary" not in fake.store
    assert "session:s1:owner" not in fake.store
    assert "session:s1:last_compact" not in fake.store
    assert fake.store["session:s2:messages"] == "keep"


def test_deleted_session_write_is_not_current():
    from app.tools.context_tools import begin_session_write, clear_session_memory, session_write_current

    fake = _FakeRedis()
    with patch("app.tools.context_tools._get_redis", return_value=fake):
        token = begin_session_write("s1")
        assert token
        assert session_write_current("s1", token) is True
        clear_session_memory("s1")
        assert session_write_current("s1", token) is False
        later = begin_session_write("s1")
        assert session_write_current("s1", later) is True
        assert session_write_current("s1", token) is False


def test_empty_inputs_rejected():
    assert ensure_session_owner("", "s1") is False
    assert ensure_session_owner("user_a", "") is False

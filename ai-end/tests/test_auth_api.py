from unittest.mock import MagicMock

import pytest


class TestAuthEnforcement:
    """验证 require_auth 强制登录，无 token 抛 401"""

    def test_require_auth_no_header_raises_401(self):
        from fastapi import HTTPException

        from app.routers._shared import require_auth
        request = MagicMock()
        request.headers.get.return_value = ""  # 没有 Authorization 头
        try:
            require_auth(request)
            raise AssertionError("应该抛 401")
        except HTTPException as e:
            assert e.status_code == 401

    def test_require_auth_invalid_token_raises_401(self):

        from fastapi import HTTPException

        from app.routers._shared import require_auth
        request = MagicMock()
        request.headers.get.return_value = "Bearer invalid_token_xxx"
        try:
            require_auth(request)
            raise AssertionError("应该抛 401")
        except HTTPException as e:
            assert e.status_code == 401

    def test_require_auth_valid_token_returns_user_id(self):
        import time

        from app.routers._shared import _token_set, require_auth
        token = "test_valid_token_abc"
        _token_set(token, "user_999", time.time() + 3600)
        request = MagicMock()
        request.headers.get.return_value = f"Bearer {token}"
        result = require_auth(request)
        assert result == "user_999"


class TestChatRequestValidation:
    """验证 ChatRequest.image_urls 防超大 payload 校验"""

    def test_normal_image_urls_accepted(self):
        from app.models import ChatRequest
        m = ChatRequest(question="hi", image_urls=["data:image/png;base64,AAAA"])
        assert m.imageUrls == ["data:image/png;base64,AAAA"]

    def test_no_image_urls_accepted(self):
        from app.models import ChatRequest
        m = ChatRequest(question="hi")
        assert m.imageUrls is None

    def test_oversized_single_url_rejected(self):
        from pydantic import ValidationError

        from app.models import ChatRequest
        with pytest.raises(ValidationError):
            ChatRequest(question="hi", image_urls=["A" * 8_500_000])

    def test_oversized_total_rejected(self):
        from pydantic import ValidationError

        from app.models import ChatRequest
        with pytest.raises(ValidationError):
            ChatRequest(question="hi", image_urls=["B" * 2_000_000] * 4)

    def test_non_string_url_rejected(self):
        from pydantic import ValidationError

        from app.models import ChatRequest
        with pytest.raises(ValidationError):
            ChatRequest(question="hi", image_urls=[123])


class TestLoginRateLimit:
    def test_only_failures_consume_quota(self):
        from app.routers import auth as auth_mod
        ip = "10.0.0.9"
        auth_mod._clear_login_failures(ip)
        for _ in range(20):
            assert auth_mod._rate_limited(ip) is False
        for _ in range(auth_mod._LOGIN_LIMIT_MAX):
            assert auth_mod._rate_limited(ip) is False
            auth_mod._record_login_failure(ip)
        assert auth_mod._rate_limited(ip) is True

    def test_redis_incr_path(self, monkeypatch):
        from app.routers import auth as auth_mod

        class _Pipe:
            def __init__(self, store):
                self.store = store
                self.ops = []

            def incr(self, key):
                self.ops.append(("incr", key))
                return self

            def expire(self, key, ttl):
                self.ops.append(("expire", key, ttl))
                return self

            def execute(self):
                out = []
                for op in self.ops:
                    if op[0] == "incr":
                        key = op[1]
                        self.store[key] = int(self.store.get(key) or 0) + 1
                        out.append(self.store[key])
                    else:
                        out.append(True)
                self.ops = []
                return out

        class _FakeRedis:
            def __init__(self):
                self.store = {}

            def get(self, key):
                val = self.store.get(key)
                return None if val is None else str(val)

            def pipeline(self):
                return _Pipe(self.store)

        fake = _FakeRedis()
        monkeypatch.setattr(auth_mod, "_login_redis", lambda: fake)
        ip = "10.0.0.8"
        assert auth_mod._rate_limited(ip) is False
        for _ in range(auth_mod._LOGIN_LIMIT_MAX):
            auth_mod._record_login_failure(ip)
        assert auth_mod._rate_limited(ip) is True
        assert fake.store[f"{auth_mod._LOGIN_KEY_PREFIX}{ip}"] == auth_mod._LOGIN_LIMIT_MAX

    def test_md5_compare_rejects_wrong_length(self):
        from app.routers.auth import _verify_password
        assert _verify_password("123456", "e10adc3949ba59abbe56e057f20f883e") is True
        assert _verify_password("123456", "deadbeef") is False
        assert _verify_password("wrong", "e10adc3949ba59abbe56e057f20f883e") is False


def test_test_account_requires_password_hash():
    from app.config import Settings
    s = Settings(
        test_account_enabled=True,
        test_account_email="demo@viewhub.com",
        test_account_password_md5="",
    )
    assert s.test_account is None

import pytest
from unittest.mock import patch, MagicMock



class TestAuthEnforcement:
    """验证 require_auth 强制登录，无 token 抛 401"""

    def test_require_auth_no_header_raises_401(self):
        from app.routers._shared import require_auth
        from fastapi import HTTPException
        request = MagicMock()
        request.headers.get.return_value = ""  # 没有 Authorization 头
        try:
            require_auth(request)
            assert False, "应该抛 401"
        except HTTPException as e:
            assert e.status_code == 401

    def test_require_auth_invalid_token_raises_401(self):
        from app.routers._shared import require_auth, _token_set
        from fastapi import HTTPException
        import time
        request = MagicMock()
        request.headers.get.return_value = "Bearer invalid_token_xxx"
        try:
            require_auth(request)
            assert False, "应该抛 401"
        except HTTPException as e:
            assert e.status_code == 401

    def test_require_auth_valid_token_returns_user_id(self):
        from app.routers._shared import require_auth, _token_set
        import time
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
        from app.models import ChatRequest
        from pydantic import ValidationError
        import pytest
        with pytest.raises(ValidationError):
            ChatRequest(question="hi", image_urls=["A" * 8_500_000])

    def test_oversized_total_rejected(self):
        from app.models import ChatRequest
        from pydantic import ValidationError
        import pytest
        with pytest.raises(ValidationError):
            ChatRequest(question="hi", image_urls=["B" * 2_000_000] * 4)

    def test_non_string_url_rejected(self):
        from app.models import ChatRequest
        from pydantic import ValidationError
        import pytest
        with pytest.raises(ValidationError):
            ChatRequest(question="hi", image_urls=[123])

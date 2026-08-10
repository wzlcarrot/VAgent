"""
端到端 API 测试：用 ASGI transport 直接驱动 FastAPI 应用，
验证认证、cookie、鉴权、参数校验等真实请求链路。

与单元测试的区别：
- 不 patch 模块内部，通过 FastAPI 官方 seam（dependency_overrides / TestClient）驱动
- 覆盖 401/403/422 等失败路径
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client():
    """进程内 TestClient：触发 lifespan、可携带 cookie、无需真实网络。

    session 级复用：避免每个测试重建 TestClient 触发 lifespan 关闭，
    导致全局 executor（workflow/checkpoint）被 shutdown 后无法再提交。
    """
    with TestClient(app) as c:
        yield c


def _login(client: TestClient, email: str = "test@viewhub.com", password: str = "123456"):
    resp = client.post("/ai/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp


class TestAuthE2E:
    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_login_sets_http_only_cookie(self, client):
        resp = _login(client)
        set_cookie = resp.headers.get("set-cookie", "")
        assert "auth_token=" in set_cookie
        assert "httponly" in set_cookie.lower()
        assert "samesite=lax" in set_cookie.lower()
        assert resp.json()["user"]["token"]

    def test_cookie_authenticates_sessions(self, client):
        _login(client)
        # cookie 由 TestClient 自动保存，无需手动带 header
        r = client.get("/ai/chat/sessions")
        assert r.status_code == 200
        assert "sessions" in r.json()

    def test_missing_auth_raises_401(self, client):
        client.cookies.clear()  # 清掉其他测试残留的登录 cookie
        r = client.get("/ai/chat/sessions")
        assert r.status_code == 401

    def test_bad_token_raises_401(self, client):
        r = client.get("/ai/chat/sessions", headers={"Authorization": "Bearer invalid_token_xxx"})
        assert r.status_code == 401

    def test_login_wrong_password_401(self, client):
        r = client.post("/ai/login", json={"email": "test@viewhub.com", "password": "wrong"})
        assert r.status_code == 401
        assert "邮箱或密码错误" in r.json()["detail"]

    def test_login_unknown_email_401_same_message(self, client):
        """防用户枚举：未知邮箱与错误密码返回同一消息"""
        r = client.post("/ai/login", json={"email": "nobody@nowhere.com", "password": "x"})
        assert r.status_code == 401
        assert r.json()["detail"] == "邮箱或密码错误"

    def test_logout_clears_cookie(self, client):
        _login(client)
        r = client.post("/ai/logout")
        assert r.status_code == 200
        # 清 cookie 后请求应 401
        assert client.get("/ai/chat/sessions").status_code == 401


class TestValidationE2E:
    def test_empty_question_rejected(self, client):
        _login(client)
        r = client.post("/ai/chat/stream", json={"question": ""})
        assert r.status_code == 422

    def test_oversized_image_url_rejected(self, client):
        _login(client)
        r = client.post("/ai/chat/stream", json={"question": "hi", "image_urls": ["A" * 8_500_000]})
        assert r.status_code == 422

    def test_oversized_total_images_rejected(self, client):
        _login(client)
        r = client.post("/ai/chat/stream", json={"question": "hi", "image_urls": ["B" * 2_000_000] * 4})
        assert r.status_code == 422

    def test_feedback_missing_params_400(self, client):
        _login(client)
        r = client.post("/ai/feedback", json={"session_id": "s1"})
        assert r.status_code == 400

    def test_feedback_invalid_value_400(self, client):
        _login(client)
        r = client.post("/ai/feedback", json={"session_id": "s1", "feedback": "bad"})
        assert r.status_code == 400


class TestAdminE2E:
    def test_admin_no_key_403(self, client):
        r = client.get("/ai/admin/stats")
        assert r.status_code == 403

    def test_admin_wrong_key_403(self, client):
        r = client.get("/ai/admin/stats", headers={"X-Admin-Key": "wrong"})
        assert r.status_code == 403

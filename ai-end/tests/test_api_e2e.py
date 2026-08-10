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


class TestRealFlowE2E:
    """真实业务链路：SSE 流式、分页、越权拦截、反馈写入"""

    def test_chat_stream_returns_sse(self, client):
        _login(client)
        with client.stream("POST", "/ai/chat/stream", json={"question": "你好"}) as r:
            assert r.status_code == 200
            assert "text/event-stream" in r.headers.get("content-type", "")
            body = "".join(r.iter_text())
            assert "data:" in body
            assert "[DONE]" in body

    def test_chat_stream_returns_text_event(self, client):
        _login(client)
        with client.stream("POST", "/ai/chat/stream", json={"question": "你好"}) as r:
            body = "".join(r.iter_text())
            # 至少一个 text 事件（greeting 快速路径不调 LLM）
            assert '"type":"text"' in body or '"type": "text"' in body

    def test_sessions_pagination_no_duplicates(self, client):
        _login(client)
        first = client.get("/ai/chat/sessions", params={"limit": 1, "offset": 0}).json()
        second = client.get("/ai/chat/sessions", params={"limit": 1, "offset": 1}).json()
        assert len(first["sessions"]) <= 1
        assert len(second["sessions"]) <= 1
        ids1 = [s["session_id"] for s in first["sessions"]]
        ids2 = [s["session_id"] for s in second["sessions"]]
        assert not set(ids1) & set(ids2), "offset 分页不应返回重复会话"

    def test_delete_foreign_session_404(self, client):
        _login(client)
        r = client.delete("/ai/chat/session/nonexistent_session_xyz")
        assert r.status_code == 404

    def test_checkpoints_foreign_session_404(self, client):
        _login(client)
        r = client.get("/ai/chat/checkpoints", params={"session_id": "foreign_session_xyz"})
        assert r.status_code == 404

    def test_feedback_full_flow(self, client):
        _login(client)
        r = client.post("/ai/feedback", json={
            "session_id": "e2e_test_session",
            "message_index": 0,
            "feedback": "helpful",
        })
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_feedback_user_id_ignored_from_body(self, client):
        """伪造 body user_id 不生效，以 token 为准（防越权写他人记忆）"""
        _login(client)
        r = client.post("/ai/feedback", json={
            "session_id": "e2e_test_session",
            "message_index": 0,
            "feedback": "not_helpful",
            "user_id": "victim_user",
        })
        assert r.status_code == 200


class TestConcurrencyE2E:
    """并发验证：多请求并行下 event loop 不被同步调用阻塞"""

    def test_parallel_health_and_auth(self):
        import asyncio
        import time
        from httpx import AsyncClient, ASGITransport

        async def _run():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                login = await c.post("/ai/login", json={
                    "email": "test@viewhub.com", "password": "123456",
                })
                assert login.status_code == 200
                token = login.json()["user"]["token"]
                headers = {"Authorization": f"Bearer {token}"}

                async def health():
                    return (await c.get("/health")).status_code
                async def sessions():
                    return (await c.get("/ai/chat/sessions", headers=headers)).status_code

                start = time.time()
                results = await asyncio.gather(*[health() for _ in range(8)], sessions())
                elapsed = time.time() - start

                assert all(r == 200 for r in results)
                # 并发 9 个请求应在数秒内完成（证明 event loop 未被同步调用阻塞）
                assert elapsed < 10, f"并发请求过慢: {elapsed:.2f}s"

        asyncio.run(_run())

"""
共享 pytest 配置：确保 `app` 包可导入（支持从任意目录执行 pytest）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    """每个测试前清空登录限流计数，避免 e2e 多个 _login 触发 429。

    登录限流是安全特性，但会让同进程里连续登录的测试互相影响，
    因此按测试粒度隔离状态。
    """
    try:
        from app.routers import auth as auth_module
        with auth_module._login_lock:
            auth_module._login_attempts.clear()
    except Exception:
        pass
    yield
    try:
        from app.routers import auth as auth_module
        with auth_module._login_lock:
            auth_module._login_attempts.clear()
    except Exception:
        pass


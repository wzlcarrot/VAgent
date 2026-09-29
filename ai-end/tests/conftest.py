"""
共享 pytest 配置：确保 `app` 包可导入（支持从任意目录执行 pytest）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _ci_ensure_agent_schema():
    """GitHub Actions 有 Postgres 服务但无 ViewHub 全量 schema，先建 Agent 表避免单测误连库失败。"""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    try:
        from app.tools.db.pool import close_global_pool
        from app.tools.db.schema import init_agent_tables

        close_global_pool()
        init_agent_tables()
    except Exception as exc:
        raise RuntimeError(f"CI Agent schema init failed: {exc}") from exc


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    """每个测试前清空登录限流计数，避免 e2e 多个 _login 触发 429。

    登录限流是安全特性，但会让同进程里连续登录的测试互相影响，
    因此按测试粒度隔离状态。
    """
    try:
        from app.routers import auth as auth_module
        auth_module._clear_login_failures()
    except Exception:
        pass
    yield
    try:
        from app.routers import auth as auth_module
        auth_module._clear_login_failures()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _reset_llm_circuit():
    """每个测试前后重置 LLM 熔断器，避免某个测试打到 open 污染后续依赖 LLM 的测试。"""
    from app.tools.llm_circuit import reset_circuit
    reset_circuit()
    yield
    reset_circuit()


@pytest.fixture(autouse=True)
def _reset_tool_governor():
    """每个测试前后清空工具调用配额，避免 Redis 计数跨测试/跨运行累积触发 ToolCallLimitExceeded。"""
    try:
        from app.harness.tool_governor import ToolGovernor
        ToolGovernor().reset_all()
    except Exception:
        pass
    yield
    try:
        from app.harness.tool_governor import ToolGovernor
        ToolGovernor().reset_all()
    except Exception:
        pass


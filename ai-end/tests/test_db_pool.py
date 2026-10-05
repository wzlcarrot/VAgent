"""连接池时区：今天/本周不跟随数据库服务器默认 UTC。"""
from unittest.mock import MagicMock, patch


def test_pool_sets_beijing_timezone():
    import app.tools.db.pool as pool_mod

    pool_mod._global_pool = None
    pool_mod._last_health_check = 0.0
    fake = MagicMock()
    with patch("app.tools.db.pool.pool.ThreadedConnectionPool", return_value=fake) as ctor, \
         patch("app.tools.db.pool._set_pool_metric"):
        created = pool_mod.get_global_pool()
    assert created is fake
    options = ctor.call_args.kwargs["options"]
    assert "TimeZone=Asia/Shanghai" in options
    assert "statement_timeout=15000" in options
    pool_mod._global_pool = None
    pool_mod._last_health_check = 0.0


def test_health_check_uses_select_and_returns_conn():
    """psycopg2 没有 ping()。健康检查失败时还要把连接还回去。"""
    import app.tools.db.pool as pool_mod

    conn = MagicMock()
    conn.closed = 0
    fake_pool = MagicMock()
    fake_pool.getconn.return_value = conn
    pool_mod._global_pool = fake_pool
    pool_mod._last_health_check = 0.0
    try:
        created = pool_mod.get_global_pool()
        assert created is fake_pool
        conn.cursor.return_value.__enter__.return_value.execute.assert_called_with("SELECT 1")
        fake_pool.putconn.assert_called_once_with(conn)
        conn.ping.assert_not_called()
    finally:
        pool_mod._global_pool = None
        pool_mod._last_health_check = 0.0

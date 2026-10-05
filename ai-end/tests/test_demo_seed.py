from unittest.mock import MagicMock, patch

from app.services.demo_seed import seed_demo_corpus


def test_seed_skipped_when_disabled():
    with patch("app.config.settings.demo_seed_enabled", False):
        seed_demo_corpus()


def test_seed_skipped_without_pool():
    with patch("app.config.settings.demo_seed_enabled", True), \
         patch("app.tools.db.pool.get_global_pool", return_value=None):
        seed_demo_corpus()


def test_seed_writes_catalog_and_behavior():
    cur = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value = cur
    pool = MagicMock()
    pool.getconn.return_value = conn
    with patch("app.config.settings.demo_seed_enabled", True), \
         patch("app.config.settings.demo_video_id", "demo01"), \
         patch("app.tools.db.pool.get_global_pool", return_value=pool):
        seed_demo_corpus()
    assert cur.execute.call_count >= 20
    pool.putconn.assert_called_once_with(conn)
    conn.commit.assert_called()
    sqls = " ".join(str(c.args[0]) for c in cur.execute.call_args_list if c.args)
    assert "demo12" in str(cur.execute.call_args_list)
    assert "video_vector_block" in sqls


def test_seed_meta_savepoint_on_create_error():
    cur = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value = cur

    def _execute(sql, *args, **kwargs):
        if "CREATE TABLE IF NOT EXISTS user_info" in str(sql):
            raise RuntimeError("viewhub schema")
        return None

    cur.execute.side_effect = _execute
    pool = MagicMock()
    pool.getconn.return_value = conn
    with patch("app.config.settings.demo_seed_enabled", True), \
         patch("app.config.settings.demo_video_id", "demo01"), \
         patch("app.tools.db.pool.get_global_pool", return_value=pool):
        seed_demo_corpus()
    assert any("ROLLBACK TO SAVEPOINT sp_demo_meta" in str(c.args[0]) for c in cur.execute.call_args_list if c.args)


def test_seed_behavior_savepoint_on_alter_error():
    cur = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value = cur

    def _execute(sql, *args, **kwargs):
        if "ALTER TABLE user_info" in str(sql):
            raise RuntimeError("no alter")
        return None

    cur.execute.side_effect = _execute
    pool = MagicMock()
    pool.getconn.return_value = conn
    with patch("app.config.settings.demo_seed_enabled", True), \
         patch("app.config.settings.demo_video_id", "demo01"), \
         patch("app.tools.db.pool.get_global_pool", return_value=pool):
        seed_demo_corpus()
    assert any("ROLLBACK TO SAVEPOINT sp_demo_behavior" in str(c.args[0]) for c in cur.execute.call_args_list if c.args)


def test_seed_rolls_back_on_error():
    pool = MagicMock()
    pool.getconn.side_effect = RuntimeError("db down")
    with patch("app.config.settings.demo_seed_enabled", True), \
         patch("app.tools.db.pool.get_global_pool", return_value=pool):
        seed_demo_corpus()


def test_register_local_video_requires_id_and_title():
    from app.services.video_indexing import register_local_video

    assert register_local_video("", "t")["success"] is False
    assert register_local_video("v1", "")["success"] is False


def test_register_local_video_writes_then_indexes():
    from app.services.video_indexing import register_local_video

    cur = MagicMock()
    with patch("app.services.video_indexing.get_cursor") as gc, \
         patch("app.services.video_indexing.RAGTools.index_video", return_value={"success": True}) as idx:
        gc.return_value.__enter__.return_value = cur
        gc.return_value.__exit__.return_value = False
        out = register_local_video("demo99", "本地片", tags="demo", introduction="简介", body="文稿")
    assert out["success"] is True
    cur.execute.assert_called()
    idx.assert_called_once_with("demo99")

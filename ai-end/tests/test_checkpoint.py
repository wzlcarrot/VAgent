"""
CheckpointManager 单元测试：覆盖持久化的韧性路径（不依赖真实 DB，mock 连接池）。

验证：
1. save() 在 executor 正常时走后台线程
2. executor 已 shutdown → 同步 fallback 写入
3. submit 失败（队列满等）→ 记日志不崩
4. DB pool 不可用 → 跳过，不抛异常
5. 底层 DB 写异常 → 记日志，不冒到调用方
6. Checkpoint dataclass 序列化
"""
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _cleanup_executor():
    """每个用例后重建单例 executor，避免用例间状态污染"""
    from app.harness.checkpoint import CheckpointManager
    yield
    CheckpointManager._executor = None


def _make_checkpoint():
    from app.harness.checkpoint import Checkpoint
    return Checkpoint(
        session_id="session-1234",
        workflow_type="video_qa",
        step_name="llm_node",
        state_snapshot={"question": "这个视频讲了什么", "answer": "答"},
        status="completed",
    )


class TestCheckpointSave:
    def test_save_submits_to_executor(self):
        from app.harness.checkpoint import CheckpointManager
        mgr = CheckpointManager()
        cp = _make_checkpoint()
        with patch.object(mgr._executor, "submit") as mock_submit:
            mgr.save(cp)
            mock_submit.assert_called_once()
            # 提交的是 _do_save，且参数是 cp
            args = mock_submit.call_args[0]
            assert args[0].__name__ == "_do_save"
            assert args[1] is cp

    def test_save_fallback_to_sync_when_executor_shutdown(self):
        from app.harness.checkpoint import CheckpointManager
        mgr = CheckpointManager()
        cp = _make_checkpoint()
        # executor 已关闭 → submit 抛 RuntimeError
        mgr._executor = MagicMock()
        mgr._executor.submit.side_effect = RuntimeError("executor shutdown")
        with patch.object(mgr, "_do_save") as mock_do_save:
            mgr.save(cp)
            mock_do_save.assert_called_once_with(cp)

    def test_save_logs_on_submit_failure(self):
        from app.harness.checkpoint import CheckpointManager
        mgr = CheckpointManager()
        cp = _make_checkpoint()
        mgr._executor = MagicMock()
        mgr._executor.submit.side_effect = Exception("queue full")
        with patch.object(mgr, "_do_save") as mock_do_save, patch(
            "app.harness.checkpoint.logger.warning"
        ) as mock_warn:
            mgr.save(cp)
            mock_do_save.assert_not_called()
            assert mock_warn.call_count >= 1

    def test_do_save_skips_when_pool_unavailable(self):
        from app.harness.checkpoint import CheckpointManager
        mgr = CheckpointManager()
        cp = _make_checkpoint()
        with patch("app.harness.checkpoint.get_global_pool", return_value=None), patch(
            "app.harness.checkpoint.logger.warning"
        ) as mock_warn:
            mgr._do_save(cp)
            assert any("跳过" in str(c.args[0]) for c in mock_warn.call_args_list)

    def test_do_save_writes_and_commits(self):
        from app.harness.checkpoint import CheckpointManager
        mgr = CheckpointManager()
        cp = _make_checkpoint()

        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        pool.getconn.return_value = conn
        conn.cursor.return_value = cursor

        with patch("app.harness.checkpoint.get_global_pool", return_value=pool), patch(
            "app.harness.checkpoint._record_step_metric"
        ):
            mgr._do_save(cp)

        cursor.execute.assert_called_once()
        conn.commit.assert_called_once()
        pool.putconn.assert_called_once_with(conn)
        # UPSERT 语句包含 INSERT 与 ON CONFLICT
        sql = cursor.execute.call_args[0][0]
        assert "INSERT INTO workflow_checkpoints" in sql
        assert "ON CONFLICT" in sql

    def test_do_save_swallows_db_error(self):
        from app.harness.checkpoint import CheckpointManager
        mgr = CheckpointManager()
        cp = _make_checkpoint()

        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.execute.side_effect = Exception("connection lost")
        pool.getconn.return_value = conn
        conn.cursor.return_value = cursor

        with patch("app.harness.checkpoint.get_global_pool", return_value=pool), patch(
            "app.harness.checkpoint.logger.error"
        ) as mock_err:
            # 不应抛异常
            mgr._do_save(cp)
        assert mock_err.call_count >= 1
        # 连接仍需归还
        pool.putconn.assert_called_once_with(conn)


class TestCheckpointSerialization:
    def test_to_dict_shape(self):
        from app.harness.checkpoint import Checkpoint
        cp = Checkpoint(
            session_id="s1",
            workflow_type="chat",
            step_name="faq_node",
            state_snapshot={"x": 1},
        )
        d = cp.to_dict()
        assert set(d) == {
            "checkpoint_id", "session_id", "workflow_type", "step_name",
            "state_snapshot", "status", "error", "created_at",
        }
        assert d["status"] == "completed"
        assert d["state_snapshot"] == {"x": 1}

    def test_to_dict_supports_error(self):
        from app.harness.checkpoint import Checkpoint
        cp = Checkpoint(
            session_id="s1",
            workflow_type="chat",
            step_name="n",
            state_snapshot={},
            status="failed",
            error="boom",
        )
        assert cp.to_dict()["status"] == "failed"
        assert cp.to_dict()["error"] == "boom"


class TestCheckpointRead:
    def test_get_returns_checkpoint(self):
        from datetime import datetime

        from app.harness.checkpoint import CheckpointManager
        mgr = CheckpointManager()

        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = ("cp1", {"q": 1}, "completed", None, datetime(2026, 8, 1))
        pool.getconn.return_value = conn
        conn.cursor.return_value = cursor

        with patch("app.harness.checkpoint.get_global_pool", return_value=pool):
            cp = mgr.get("s1", "chat", "faq_node")

        assert cp is not None
        assert cp.checkpoint_id == "cp1"
        assert cp.state_snapshot == {"q": 1}
        assert cp.step_name == "faq_node"

    def test_get_returns_none_when_no_row(self):
        from app.harness.checkpoint import CheckpointManager
        mgr = CheckpointManager()

        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        pool.getconn.return_value = conn
        conn.cursor.return_value = cursor

        with patch("app.harness.checkpoint.get_global_pool", return_value=pool):
            assert mgr.get("s1", "chat", "faq_node") is None

    def test_get_returns_none_when_pool_unavailable(self):
        from app.harness.checkpoint import CheckpointManager
        mgr = CheckpointManager()
        with patch("app.harness.checkpoint.get_global_pool", return_value=None):
            assert mgr.get("s1", "chat", "faq_node") is None

    def test_get_swallows_db_error(self):
        from app.harness.checkpoint import CheckpointManager
        mgr = CheckpointManager()

        pool = MagicMock()
        conn = MagicMock()
        conn.cursor.side_effect = Exception("read failed")
        pool.getconn.return_value = conn

        with patch("app.harness.checkpoint.get_global_pool", return_value=pool), patch(
            "app.harness.checkpoint.logger.error"
        ):
            assert mgr.get("s1", "chat", "faq_node") is None

    def test_get_last_completed_queries_with_ordering(self):
        from datetime import datetime

        from app.harness.checkpoint import CheckpointManager
        mgr = CheckpointManager()

        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = ("cp9", "summary_node", {"a": 1}, "completed", None, datetime(2026, 8, 2))
        pool.getconn.return_value = conn
        conn.cursor.return_value = cursor

        with patch("app.harness.checkpoint.get_global_pool", return_value=pool):
            cp = mgr.get_last_completed("s1", "recommend")

        assert cp.step_name == "summary_node"
        sql = cursor.execute.call_args[0][0]
        assert "ORDER BY created_at DESC" in sql
        assert "status = 'completed'" in sql

    def test_list_steps_returns_step_names(self):
        from app.harness.checkpoint import CheckpointManager
        mgr = CheckpointManager()

        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = [("a",), ("b",)]
        pool.getconn.return_value = conn
        conn.cursor.return_value = cursor

        with patch("app.harness.checkpoint.get_global_pool", return_value=pool):
            assert mgr.list_steps("s1", "chat") == ["a", "b"]

    def test_list_step_details_returns_structured(self):
        from datetime import datetime

        from app.harness.checkpoint import CheckpointManager
        mgr = CheckpointManager()

        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = [("profile_node", "completed", datetime(2026, 8, 1))]
        pool.getconn.return_value = conn
        conn.cursor.return_value = cursor

        with patch("app.harness.checkpoint.get_global_pool", return_value=pool):
            details = mgr.list_step_details("s1", "recommend")

        assert details[0]["step_name"] == "profile_node"
        assert details[0]["status"] == "completed"
        assert details[0]["created_at"] is not None

    def test_clear_session_commits_delete(self):
        from app.harness.checkpoint import CheckpointManager
        mgr = CheckpointManager()

        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        pool.getconn.return_value = conn
        conn.cursor.return_value = cursor

        with patch("app.harness.checkpoint.get_global_pool", return_value=pool):
            assert mgr.clear_session("s1") is True

        cursor.execute.assert_called_once()
        assert "DELETE FROM workflow_checkpoints" in cursor.execute.call_args[0][0]
        conn.commit.assert_called_once()

    def test_clear_session_returns_false_when_pool_unavailable(self):
        from app.harness.checkpoint import CheckpointManager
        mgr = CheckpointManager()
        with patch("app.harness.checkpoint.get_global_pool", return_value=None):
            assert mgr.clear_session("s1") is False

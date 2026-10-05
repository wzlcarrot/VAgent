"""HITL ask 审批 + Stop/PreCompact hook 事件。"""
import queue
import threading
from unittest.mock import patch

import pytest

from app.exceptions import ToolApprovalRequired
from app.harness.hitl_approval import (
    create_approval,
    reset_approvals,
    resolve_approval,
    wait_for_decision,
)
from app.harness.hooks import HookEvent, HooksManager
from app.harness.tool_governor import ToolGovernor
from app.harness.tool_policy import load_policy, resolve_rule
from app.streaming.event_bridge import approval_event


@pytest.fixture(autouse=True)
def _clean_hitl():
    # 审批缓存走内存路径，避免 Redis 跨测试泄漏
    with patch("app.harness.hitl_approval._cache_redis", return_value=None):
        reset_approvals()
        yield
        reset_approvals()


def test_approval_event_shape():
    evt = approval_event(
        approval_id="abc", tool="recommend_videos", label="个性化推荐",
        agent="recommend_workflow", arguments_preview="{}", timeout_s=60,
    )
    assert evt["type"] == "approval"
    assert evt["approval_id"] == "abc"
    assert evt["tool"] == "recommend_videos"


def test_resolve_approve_wakes_waiter():
    req = create_approval(
        session_id="s1", agent="recommend_workflow",
        tool_name="recommend_videos", arguments={"q": "1"}, timeout_s=5,
    )
    out = {}

    def _wait():
        out["d"] = wait_for_decision(req)

    t = threading.Thread(target=_wait)
    t.start()
    assert resolve_approval(req.approval_id, "approve", session_id="s1")["ok"]
    t.join(timeout=2)
    assert out.get("d") == "approve"


def test_gate_ask_hitl_approve():
    with patch("app.config.settings.harness_enabled", True), \
         patch("app.config.settings.hitl_enabled", True), \
         patch("app.config.settings.hitl_auto_decision", "approve"), \
         patch("app.harness.tool_governor._policy_limits", return_value=(5, 10.0, "ask", 1000, False)), \
         patch("app.tools.tool_registry.ToolSandbox.validate_call", return_value=True):
        gov = ToolGovernor()
        result = gov.gate("sid", "recommend_workflow", "recommend_videos", {}, lambda: "ok")
    assert result == "ok"


def test_gate_ask_hitl_deny():
    with patch("app.config.settings.harness_enabled", True), \
         patch("app.config.settings.hitl_enabled", True), \
         patch("app.config.settings.hitl_auto_decision", "deny"), \
         patch("app.harness.tool_governor._policy_limits", return_value=(5, 10.0, "ask", 1000, False)):
        gov = ToolGovernor()
        with pytest.raises(ToolApprovalRequired):
            gov.gate("sid", "recommend_workflow", "recommend_videos", {}, lambda: "ok")


def test_gate_ask_fail_closed_without_hitl():
    with patch("app.config.settings.harness_enabled", True), \
         patch("app.config.settings.hitl_enabled", False), \
         patch("app.harness.tool_governor._policy_limits", return_value=(5, 10.0, "ask", 1000, False)):
        gov = ToolGovernor()
        with pytest.raises(ToolApprovalRequired):
            gov.gate("sid", "chat_workflow", "recommend_videos", {}, lambda: "x")


def test_recommend_policy_is_allow():
    load_policy(force=True)
    from app.agents.workflows.constants import WorkflowType
    rule = resolve_rule(WorkflowType.RECOMMEND, "recommend_videos")
    assert rule.decision == "allow"


def test_stop_and_pre_compact_hook_events():
    mgr = HooksManager()
    seen = []

    def on_stop(ctx):
        seen.append("stop")
        return {"stop_reason": "demo"}

    def on_pre(ctx):
        seen.append("pre_compact")

    mgr.register(HookEvent.STOP, on_stop)
    mgr.register(HookEvent.PRE_COMPACT, on_pre)
    assert HookEvent.STOP in HookEvent.all()
    assert HookEvent.PRE_COMPACT in HookEvent.all()
    ctx = mgr.trigger(HookEvent.STOP, session_id="s")
    assert ctx["stop_reason"] == "demo"
    mgr.trigger(HookEvent.PRE_COMPACT, session_id="s")
    assert seen == ["stop", "pre_compact"]


def test_emit_approval_via_progress_queue():
    from app.harness.hitl_approval import emit_approval_request
    from app.harness.tool_progress import reset_tool_progress_queue, set_tool_progress_queue

    q: queue.Queue = queue.Queue()
    token = set_tool_progress_queue(q)
    try:
        req = create_approval(
            session_id="s", agent="a", tool_name="recommend_videos", arguments={},
        )
        emit_approval_request(req)
        evt = q.get_nowait()
        assert evt["type"] == "approval"
        assert evt["approval_id"] == req.approval_id
    finally:
        reset_tool_progress_queue(token)
        reset_approvals()


class TestApprovalCache:
    def test_record_then_approved(self):
        from app.harness import hitl_approval as h
        h.reset_approvals()
        with patch("app.tools.context_tools._get_redis", return_value=None), \
             patch("app.config.settings.hitl_approval_cache_ttl", 3600):
            assert h.is_approved("s1", "chat", "recommend") is False
            h.record_approval("s1", "chat", "recommend")
            assert h.is_approved("s1", "chat", "recommend") is True
            # 会话 / agent 隔离
            assert h.is_approved("s2", "chat", "recommend") is False
            assert h.is_approved("s1", "video", "recommend") is False

    def test_cache_disabled_when_ttl_zero(self):
        from app.harness import hitl_approval as h
        h.reset_approvals()
        with patch("app.config.settings.hitl_approval_cache_ttl", 0):
            h.record_approval("s1", "a", "t")
            assert h.is_approved("s1", "a", "t") is False

    def test_gate_skips_prompt_when_cached(self):
        from app.harness import hitl_approval as h
        h.reset_approvals()
        with patch("app.config.settings.harness_enabled", True), \
             patch("app.config.settings.hitl_enabled", True), \
             patch("app.harness.tool_governor._policy_limits",
                   return_value=(5, 10.0, "ask", 1000, False)), \
             patch("app.harness.hitl_approval.is_approved", return_value=True), \
             patch("app.tools.tool_registry.ToolSandbox.validate_call", return_value=True), \
             patch("app.harness.hitl_approval.create_approval") as mock_create:
            gov = ToolGovernor()
            out = gov.gate("sid", "chat_workflow", "recommend_videos", {}, lambda: "ok")
        assert out == "ok"
        mock_create.assert_not_called()  # 已缓存 → 不再弹审批

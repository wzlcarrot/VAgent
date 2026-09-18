"""通用 Agent Loop 执行引擎测试。"""
import time

from app.agents.react_guard import DuplicateCallGuard
from app.harness.agent_loop import (
    STOP_ANSWERED,
    STOP_DUPLICATE,
    STOP_ERROR,
    STOP_MAX_STEPS,
    STOP_SUFFICIENT,
    STOP_TIMEOUT,
    AgentStep,
    Observation,
    ToolCall,
    normalize_tool_calls,
    parse_tool_call,
    run_agent_loop,
    to_openai_tool_calls,
    wrap_observation,
)


def _noop_observe(call, obs):
    pass


def test_loop_answers_without_tools():
    out = run_agent_loop(
        messages=[], decide=lambda s, m: AgentStep(calls=[], content="你好"),
        execute=lambda c: Observation("x"), observe=_noop_observe, max_steps=3,
    )
    assert out.answer == "你好"
    assert out.stop_reason == STOP_ANSWERED
    assert out.steps == 1
    assert out.tools == []


def test_loop_executes_tool_then_answers():
    seen = []

    def decide(step, msgs):
        if not seen:
            return AgentStep(calls=[ToolCall("t", {"q": "a"}, "c1")])
        return AgentStep(calls=[], content="done")

    out = run_agent_loop(
        messages=[], decide=decide,
        execute=lambda c: Observation("obs", data=c.name),
        observe=lambda c, o: seen.append(o.data),
        max_steps=3,
    )
    assert out.answer == "done"
    assert out.stop_reason == STOP_ANSWERED
    assert out.tools == ["t"]
    assert seen == ["t"]
    assert out.steps == 2


def test_loop_stops_at_max_steps():
    out = run_agent_loop(
        messages=[],
        decide=lambda s, m: AgentStep(calls=[ToolCall("t", {"q": str(s)}, f"c{s}")]),
        execute=lambda c: Observation("o"),
        observe=_noop_observe,
        max_steps=2,
        guard=DuplicateCallGuard(),
    )
    assert out.stop_reason == STOP_MAX_STEPS
    assert out.steps == 2
    assert out.tools == ["t", "t"]


def test_loop_nudges_then_force_stops_on_duplicate():
    out = run_agent_loop(
        messages=[],
        decide=lambda s, m: AgentStep(calls=[ToolCall("t", {"q": "same"}, "c")]),
        execute=lambda c: Observation("o"),
        observe=_noop_observe,
        max_steps=5,
        guard=DuplicateCallGuard(),
        nudge_after=1,
        force_stop_after=2,
    )
    assert out.stop_reason == STOP_DUPLICATE
    assert out.steps == 3  # 1 次正常执行 + 1 次 nudge + 1 次强制停
    assert out.nudges == 2
    assert out.tools == ["t"]  # 重复调用不再真正执行工具


def test_loop_timeout():
    def decide(step, msgs):
        time.sleep(0.02)
        return AgentStep(calls=[ToolCall("t", {"q": str(step)}, f"c{step}")])

    out = run_agent_loop(
        messages=[], decide=decide, execute=lambda c: Observation("o"),
        observe=_noop_observe, max_steps=5, deadline_seconds=0.001,
    )
    assert out.stop_reason == STOP_TIMEOUT
    assert out.steps == 1


def test_loop_error_when_decide_returns_none():
    out = run_agent_loop(
        messages=[], decide=lambda s, m: None, execute=lambda c: Observation("o"),
        observe=_noop_observe, max_steps=3,
    )
    assert out.stop_reason == STOP_ERROR
    assert out.steps == 1


def test_loop_should_stop_reason():
    out = run_agent_loop(
        messages=[],
        decide=lambda s, m: AgentStep(calls=[ToolCall("t", {"q": str(s)}, f"c{s}")]),
        execute=lambda c: Observation("o"),
        observe=_noop_observe,
        max_steps=5,
        should_stop=lambda: STOP_SUFFICIENT,
    )
    assert out.stop_reason == STOP_SUFFICIENT
    assert out.steps == 1


def test_loop_finalize_when_no_answer():
    out = run_agent_loop(
        messages=[],
        decide=lambda s, m: AgentStep(calls=[ToolCall("t", {"q": str(s)}, f"c{s}")]),
        execute=lambda c: Observation("o"),
        observe=_noop_observe,
        max_steps=1,
        finalize=lambda: "兜底",
    )
    assert out.answer == "兜底"
    assert out.stop_reason == STOP_MAX_STEPS


def test_wrap_observation():
    assert "工具无返回内容" in wrap_observation("")
    assert wrap_observation("ok") == "ok"
    assert "ERROR" in wrap_observation("boom", is_error=True)


def test_normalize_tool_calls():
    resp = {"tool_calls": [
        {"tool_call_id": "c1", "tool_name": "a", "arguments": {"x": 1}},
        {"id": "c2", "function": {"name": "b", "arguments": '{"y": 2}'}},
    ]}
    calls = normalize_tool_calls(resp)
    assert [c.name for c in calls] == ["a", "b"]
    assert calls[0].args == {"x": 1}
    assert calls[1].args == {"y": 2}
    assert calls[1].call_id == "c2"

    single = normalize_tool_calls({"tool_name": "a", "arguments": {"x": 1}})
    assert len(single) == 1 and single[0].name == "a"

    assert normalize_tool_calls({"tool_call": False, "content": "x"}) == []


def test_to_openai_tool_calls():
    out = to_openai_tool_calls([ToolCall("a", {"x": 1}, "c1")])
    assert out[0]["id"] == "c1"
    assert out[0]["function"]["name"] == "a"
    assert out[0]["function"]["arguments"] == '{"x": 1}'


def test_parse_tool_call_variants():
    assert parse_tool_call({"tool_name": "a", "arguments": {"x": 1}})[0] == "a"
    assert parse_tool_call({"function": {"name": "b", "arguments": '{"y":2}'}})[0] == "b"
    assert parse_tool_call({}) == ("", {})

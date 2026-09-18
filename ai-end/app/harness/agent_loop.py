"""
通用 Agent Loop 执行引擎。

对标成熟框架（本机 `开源源码参考/`）：
- deepseek-harness `ReactLoopAgent`（packages/core/agent-loop/src/agent.ts）
- kimi-cli `KimiSoul._agent_loop` + 复用原语 `kosong.step()`
- AgentScope `ReActAgent`（ragent 的依赖）

把"决策 → 执行 → 观察 → 终止"抽成一个可复用引擎，chat / video_qa 两个 agent 共用，
避免"改一处忘另一处"（历史上 chat 的 tool_call 解析 bug 就是只修了一边）。

借鉴的四个模式：
1. **typed stop_reason**（kimi `StepStopReason`、deepseek `TurnEndReasonMap`）：
   停止原因是枚举，不是布尔，便于统计与分支。
2. **重复调用先 nudge 再停**（deepseek `repeat-tool-reminder`、kimi 3/5/8→12）：
   连续重复调用时先把提醒塞进 observation 让模型自我修正，超过阈值才强制停。
3. **统一 observation 格式**（kimi `<system>ERROR:</system>` / "Tool output is empty."）：
   空结果 / 工具异常有统一包装，模型知道发生了什么。
4. **引擎级预算**：max_steps + wall-clock deadline。
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)

# ─── stop_reason（typed enum）───
STOP_ANSWERED = "answered"        # 模型给出最终回答
STOP_MAX_STEPS = "max_steps"      # 到达步数上限
STOP_DUPLICATE = "duplicate_repeat"  # 连续重复调用，强制停
STOP_TIMEOUT = "timeout"          # 循环 wall-clock 预算耗尽
STOP_ERROR = "error"              # 模型调用失败
STOP_SUFFICIENT = "sufficient"    # 调用方判定证据已足够

_REPEAT_REMINDER = (
    "注意：你刚刚用**完全相同的参数**重复调用了同一个工具，返回结果不会变化。"
    "请先分析已经拿到的结果：如果还不够，换一个**不同的关键词或角度**再试，不要重复同样的调用。"
)
_FORCE_STOP_REMINDER = (
    "你已经连续多次重复同样的工具调用。请立即停止调用工具，基于已有信息直接给出回答。"
)


class DuplicateGuard(Protocol):
    """重复调用检测器协议（由调用方注入，引擎不依赖具体实现）。"""

    def is_duplicate(self, tool_name: str, args: Optional[Dict[str, Any]]) -> bool: ...


@dataclass
class ToolCall:
    name: str
    args: Dict[str, Any] = field(default_factory=dict)
    call_id: str = "call-0"


@dataclass
class Observation:
    """一次工具执行的观察结果。

    text: 回灌给模型的内容（已做空/错误包装）
    data: 原始结果，供调用方 `observe` 更新自身状态
    is_error: 是否执行失败
    """

    text: str
    data: Any = None
    is_error: bool = False


@dataclass
class AgentStep:
    """一次模型决策的归一化结果：calls 为空表示模型直接作答。"""

    calls: List[ToolCall] = field(default_factory=list)
    content: str = ""


@dataclass
class LoopOutcome:
    answer: str
    stop_reason: str
    steps: int
    tools: List[str]
    nudges: int = 0


# ─── 协议工具（两个 agent 共用，避免重复实现）───


def parse_tool_call(tc: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    """兼容两种 tool_call 结构：

    - 规范化格式：``{"tool_name", "arguments"}``
    - OpenAI 原生格式：``{"function": {"name", "arguments"}}``

    修复背景：chat ReAct 原先只读 ``tc["function"]["name"]``，而 ``chat_with_tools``
    返回的是规范化格式，导致工具名恒为空串、工具从未真正执行。
    """
    name = tc.get("tool_name") or ""
    args = tc.get("arguments")
    if not name:
        fn = tc.get("function") or {}
        name = fn.get("name") or ""
        if args is None:
            raw = fn.get("arguments")
            if isinstance(raw, str):
                try:
                    args = json.loads(raw)
                except json.JSONDecodeError:
                    args = {}
            elif isinstance(raw, dict):
                args = raw
    if not isinstance(args, dict):
        args = {}
    return name, args


def normalize_tool_calls(resp: Dict[str, Any]) -> List[ToolCall]:
    """把 chat_with_tools 的多种返回形态归一化为 ToolCall 列表。"""
    calls: List[ToolCall] = []
    for i, tc in enumerate(resp.get("tool_calls") or []):
        name, args = parse_tool_call(tc)
        if not name:
            continue
        calls.append(ToolCall(
            name=name,
            args=args,
            call_id=tc.get("tool_call_id") or tc.get("id") or f"call-{i}",
        ))
    if not calls and resp.get("tool_name"):
        calls.append(ToolCall(
            name=resp["tool_name"],
            args=resp.get("arguments") or {},
            call_id=resp.get("tool_call_id") or "call-0",
        ))
    return calls


def to_openai_tool_calls(calls: List[ToolCall]) -> List[Dict[str, Any]]:
    """转成 OpenAI 兼容的 assistant.tool_calls 结构，供下一轮 messages 使用。"""
    return [
        {
            "id": c.call_id,
            "type": "function",
            "function": {"name": c.name, "arguments": json.dumps(c.args, ensure_ascii=False)},
        }
        for c in calls
    ]


def wrap_observation(text: str, is_error: bool = False) -> str:
    """统一 observation 格式：空结果 / 异常都有明确前缀（借鉴 kimi）。"""
    body = (text or "").strip()
    if is_error:
        return f"<system>ERROR: {body or '工具执行失败'}</system>"
    if not body:
        return "（工具无返回内容）"
    return body


# ─── 引擎 ───


def run_agent_loop(
    *,
    messages: List[Dict[str, Any]],
    decide: Callable[[int, List[Dict[str, Any]]], Optional[AgentStep]],
    execute: Callable[[ToolCall], Observation],
    observe: Callable[[ToolCall, Observation], None],
    max_steps: int,
    finalize: Optional[Callable[[], str]] = None,
    should_stop: Optional[Callable[[], Optional[str]]] = None,
    guard: Optional[DuplicateGuard] = None,
    nudge_after: int = 1,
    force_stop_after: int = 2,
    deadline_seconds: float = 0.0,
    log_tag: str = "agent_loop",
) -> LoopOutcome:
    """驱动一次 bounded ReAct 循环。

    Args:
        messages: 初始消息（会被原地追加 assistant / tool 消息）
        decide: ``(step, messages) -> AgentStep | None``；None 表示模型调用失败
        execute: 执行一次工具调用，返回 Observation
        observe: 收到观察后更新调用方状态（累积证据、判充足等）
        max_steps: 步数上限
        finalize: 循环结束仍无回答时的兜底生成（可选）
        should_stop: 返回非空 stop_reason 则提前终止（可选，如"证据已足够"）
        guard: 重复调用检测器（可选）
        nudge_after: 连续重复达到该次数时注入提醒
        force_stop_after: 连续重复达到该次数时强制终止
        deadline_seconds: 循环 wall-clock 预算（0=不限制）
        log_tag: 日志/trace 标签
    """
    max_steps = max(1, int(max_steps))
    tools_called: List[str] = []
    nudges = 0
    streak = 0
    answer = ""
    steps = 0
    stop_reason = STOP_MAX_STEPS
    started = time.monotonic()

    for step in range(max_steps):
        if deadline_seconds and (time.monotonic() - started) > deadline_seconds:
            stop_reason = STOP_TIMEOUT
            logger.warning("%s: loop deadline exceeded at step %d", log_tag, step + 1)
            break

        decision = decide(step, messages)
        steps = step + 1
        if decision is None:
            stop_reason = STOP_ERROR
            logger.warning("%s: model call failed at step %d", log_tag, steps)
            break

        if not decision.calls:
            answer = (decision.content or "").strip()
            stop_reason = STOP_ANSWERED
            break

        messages.append({
            "role": "assistant",
            "content": decision.content or "",
            "tool_calls": to_openai_tool_calls(decision.calls),
        })

        duplicate_hit = False
        for call in decision.calls:
            if guard is not None and guard.is_duplicate(call.name, call.args):
                duplicate_hit = True
                # 仍要回应每个 tool_call id：用提醒文本作为观察回灌（不执行工具）
                attempt = streak + 1
                if attempt >= force_stop_after:
                    reminder = _FORCE_STOP_REMINDER
                elif attempt >= nudge_after:
                    reminder = _REPEAT_REMINDER
                else:
                    reminder = "（已跳过与前一次完全相同的调用）"
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.call_id,
                    "name": call.name,
                    "content": reminder,
                })
                continue
            tools_called.append(call.name)
            obs = execute(call)
            observe(call, obs)
            messages.append({
                "role": "tool",
                "tool_call_id": call.call_id,
                "name": call.name,
                "content": wrap_observation(obs.text, obs.is_error),
            })

        if duplicate_hit:
            streak += 1
            nudges += 1
            logger.info("%s: duplicate call streak=%d at step %d", log_tag, streak, steps)
            if streak >= force_stop_after:
                stop_reason = STOP_DUPLICATE
                break
        else:
            streak = 0

        if should_stop is not None:
            reason = should_stop()
            if reason:
                stop_reason = reason
                break
    else:
        stop_reason = STOP_MAX_STEPS

    if not answer and finalize is not None:
        answer = finalize() or ""

    outcome = LoopOutcome(
        answer=answer,
        stop_reason=stop_reason,
        steps=steps,
        tools=tools_called,
        nudges=nudges,
    )
    logger.info(
        "%s done stop_reason=%s steps=%d tools=%d nudges=%d",
        log_tag, outcome.stop_reason, outcome.steps, len(outcome.tools), outcome.nudges,
    )
    try:
        from app.harness.run_trace import trace_event
        trace_event(
            "agent_loop_end",
            tag=log_tag,
            stop_reason=outcome.stop_reason,
            steps=outcome.steps,
            tools=outcome.tools,
            nudges=outcome.nudges,
        )
    except Exception:
        pass
    return outcome

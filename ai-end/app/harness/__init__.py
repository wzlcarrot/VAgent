"""
Agent Harness —— 把"可靠性"做成基础设施

解决 5 个核心问题：
1. Agent 状态为什么会偏移？ → Checkpoint 每个节点落库
2. 工具调用为什么不会乱？ → ToolGovernor 限流/超时/追踪
3. 上下文为什么不会越堆越乱？ → Context 三层隔离（短期/长期/session）
4. 中间断了我怎么恢复？ → resume_from_checkpoint()
5. 怎么事后复盘？ → run_artifacts 全量 trace

模块划分：
- checkpoint.py   状态持久化 + 断点恢复
- tool_governor.py  工具调用治理
"""

from app.exceptions import ToolAccessDenied, ToolCallLimitExceeded, ToolCallTimeout
from app.harness.checkpoint import Checkpoint, CheckpointManager
from app.harness.run_trace import begin_run, finish_run, list_runs, read_trace, trace_event
from app.harness.tool_governor import ToolGovernor
from app.harness.tool_policy import load_policy, resolve_rule

__all__ = [
    "Checkpoint",
    "CheckpointManager",
    "ToolGovernor",
    "ToolCallLimitExceeded",
    "ToolCallTimeout",
    "ToolAccessDenied",
    "begin_run",
    "finish_run",
    "trace_event",
    "read_trace",
    "list_runs",
    "load_policy",
    "resolve_rule",
]

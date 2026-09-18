#!/usr/bin/env python3
"""离线回放 Run Trace JSONL → 人类可读 timeline / Mermaid。"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.harness.run_trace import list_runs, read_trace  # noqa: E402

EVENT_LABELS = {
    "run_start": "▶ 开始",
    "run_end": "■ 结束",
    "route_decision": "🔀 路由",
    "cot_intent": "🧠 意图(CoT)",
    "workflow_dispatch": "📦 派发",
    "supervisor_arbitrate": "⚖ 仲裁",
    "checkpoint": "💾 Checkpoint",
    "tool_start": "🔧 工具开始",
    "tool_end": "✅ 工具完成",
    "tool_rejected": "⛔ 工具拒绝",
    "tool_needs_approval": "⏸ 待审批",
    "tool_approved": "👍 审批通过",
    "tool_approval_cached": "♻ 审批缓存",
    "llm_retry": "🔁 LLM 重试",
    "corrective_applied": "🩹 纠正触发",
    "corrective_node": "🩹 纠正节点",
    "critic_applied": "🔍 评审标记",
    "critic_issue": "🔍 评审问题",
    "agent_loop_end": "🏁 Loop 结束",
}


def format_timeline(events: list) -> str:
    lines = ["=" * 60, "Run Trace Timeline", "=" * 60]
    for ev in events:
        label = EVENT_LABELS.get(ev.get("type", ""), ev.get("type", "?"))
        payload = ev.get("payload") or {}
        detail = ", ".join(f"{k}={v}" for k, v in payload.items() if v is not None)
        lines.append(f"[{ev.get('seq', '?'):03d}] {label}  {detail}")
    return "\n".join(lines)


def format_mermaid(events: list) -> str:
    lines = ["```mermaid", "flowchart TD"]
    prev = "START([开始])"
    idx = 0
    for ev in events:
        et = ev.get("type", "unknown")
        if et in ("run_start", "run_end"):
            continue
        node_id = f"N{idx}"
        payload = ev.get("payload") or {}
        short = et
        if et == "route_decision":
            short = f"route\\n{payload.get('workflow', '')}"
        elif et == "tool_start":
            short = f"tool\\n{payload.get('tool', '')}"
        elif et == "checkpoint":
            short = f"cp\\n{payload.get('step', '')}"
        lines.append(f'  {prev} --> {node_id}["{short}"]')
        prev = node_id
        idx += 1
    lines.append(f"  {prev} --> END([结束])")
    lines.append("```")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Replay VAgent run trace")
    parser.add_argument("--session", required=True, help="session_id")
    parser.add_argument("--run", help="run_id (omit to list runs)")
    parser.add_argument("--mermaid", action="store_true", help="output mermaid diagram")
    args = parser.parse_args()

    if not args.run:
        runs = list_runs(args.session)
        if not runs:
            print("No traces found.")
            return
        print(json.dumps({"session_id": args.session, "runs": runs}, ensure_ascii=False, indent=2))
        return

    events = read_trace(args.session, args.run)
    if not events:
        print(f"No events for run {args.run}")
        return
    if args.mermaid:
        print(format_mermaid(events))
    else:
        print(format_timeline(events))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
ReAct Agent 评测 —— 路由准确率 + 工具选择准确率 + 平均步数。

评测方式：
  - 路由：真实 Router（keyword / 语义 / LLM 融合）
  - 工具选择 / 步数：真实 ReAct 循环（模型自主决定调哪个工具、几步结束）
  - 检索后端：mock 成固定证据，摆脱对 DB / pgvector 的依赖

用法:
  cd ai-end
  python3 scripts/eval_react_metrics.py              # 离线 replay（默认，零 token）
  python3 scripts/eval_react_metrics.py --live       # 真实 LLM 决策（需 DEEPSEEK_API_KEY）
  python3 scripts/eval_react_metrics.py --live --limit 10
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "react_eval_cases.jsonl"
VIDEO_ID = "video_demo_001"
SESSION_ID = "eval_react"

# mock 检索结果：让 ReAct 能拿到“足够证据”后自行收口，避免依赖真实 DB
CANNED_CHUNKS: List[Dict[str, Any]] = [
    {
        "video_id": VIDEO_ID,
        "content": "本视频介绍了 ViewHub 平台的核心功能与使用方式，包含投稿、弹幕、收藏等。",
        "block_type": "subtitle",
        "score": 0.82,
        "start": 0.0,
        "end": 6.0,
    },
    {
        "video_id": VIDEO_ID,
        "content": "作者在片中演示了从上传到发布视频的完整流程。",
        "block_type": "subtitle",
        "score": 0.74,
        "start": 6.0,
        "end": 12.0,
    },
]
CANNED_DOCS: List[Dict[str, Any]] = [
    {"content": "ViewHub 支持视频投稿、实时弹幕、点赞收藏与 AI 智能助手。", "score": 0.8},
    {"content": "上传视频：进入创作中心，点击上传并按提示填写标题与标签。", "score": 0.7},
]

REACT_WORKFLOWS = {"video_qa_workflow", "chat_workflow"}


def load_cases() -> List[dict]:
    rows = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _install_mocks() -> None:
    """把检索后端替换为固定证据，评测只关注“模型怎么决策”，不关注 DB。"""
    import app.agents.chat_react as chat_react
    import app.agents.video_qa_react as video_qa_react

    chat_react._exec_tool = lambda name, args, session_id: list(CANNED_DOCS)  # type: ignore[assignment]
    video_qa_react._execute_search_tool = (  # type: ignore[assignment]
        lambda session_id, video_id, query, title, tags, top_k: (list(CANNED_CHUNKS), True)
    )


def _configure_mode(live: bool) -> None:
    from app.config import settings

    settings.video_qa_react_enabled = True
    if live:
        settings.demo_mode = False
        settings.llm_replay_enabled = False
    else:
        settings.demo_mode = True


def run_case(tc: dict, live: bool) -> Dict[str, Any]:
    from app.agents.chat_react import run_chat_react
    from app.agents.router import Router
    from app.agents.video_qa_react import run_video_qa_react_retrieval

    q = tc["q"]
    ctx = tc.get("ctx") or {}
    expected = tc["expected"]
    expected_tool = tc.get("expected_tool")

    router = Router()
    decision = router.hybrid_route_full(q, ctx)
    routed = decision.workflow_type

    tools: List[str] = []
    steps = 0
    stop_reason = ""
    error = ""
    try:
        if routed == "video_qa_workflow":
            _knowledge, _suff, steps, _note, stop_reason = run_video_qa_react_retrieval(
                video_id=ctx.get("video_id") or VIDEO_ID,
                question=q,
                title="ViewHub 平台介绍",
                tags="平台,功能",
                session_id=SESSION_ID,
            )
            if steps > 0:
                tools = ["search_video_chunks"]
        elif routed == "chat_workflow":
            res = run_chat_react(q, session_id=SESSION_ID)
            steps = int(res.get("react_steps") or 0)
            tools = list(res.get("react_tools") or [])
            stop_reason = res.get("react_stop_reason") or ""
    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {e}"

    return {
        "q": q,
        "expected": expected,
        "routed": routed,
        "method": decision.method,
        "expected_tool": expected_tool,
        "tools": tools,
        "steps": steps,
        "stop_reason": stop_reason,
        "error": error,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="真实 LLM 决策（默认 replay 离线）")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--show-errors", action="store_true")
    args = parser.parse_args()

    cases = load_cases()
    if args.limit:
        cases = cases[: args.limit]

    _install_mocks()
    _configure_mode(args.live)

    mode = "live(真实 LLM)" if args.live else "replay(离线)"
    print(f"模式: {mode}   用例: {len(cases)}")

    rows: List[Dict[str, Any]] = []
    t0 = time.time()
    for i, tc in enumerate(cases, 1):
        rows.append(run_case(tc, args.live))
        if i % 10 == 0 or i == len(cases):
            print(f"  进度 {i}/{len(cases)}  已用 {time.time() - t0:.0f}s", flush=True)
    elapsed = time.time() - t0

    total = len(rows)
    route_ok = sum(1 for r in rows if r["routed"] == r["expected"])

    # 工具选择：只在路由正确、且属于 ReAct workflow 的样本上评
    tool_denom = [r for r in rows if r["routed"] == r["expected"] and r["routed"] in REACT_WORKFLOWS]
    tool_ok = 0
    for r in tool_denom:
        got = r["tools"][0] if r["tools"] else None
        if got == r["expected_tool"]:
            tool_ok += 1

    step_rows = [r for r in rows if r["routed"] in REACT_WORKFLOWS and r["steps"] > 0]
    avg_steps = sum(r["steps"] for r in step_rows) / max(len(step_rows), 1)

    dist: Dict[int, int] = defaultdict(int)
    for r in step_rows:
        dist[r["steps"]] += 1

    stop_dist: Dict[str, int] = defaultdict(int)
    for r in step_rows:
        stop_dist[r.get("stop_reason") or "-"] += 1

    errors = [r for r in rows if r["error"]]

    print("=" * 58)
    print("  ReAct Agent 评测")
    print("=" * 58)
    print(f"  路由准确率      {route_ok}/{total}   {route_ok / max(total, 1) * 100:.1f}%")
    print(f"  工具选择准确率  {tool_ok}/{len(tool_denom)}   {tool_ok / max(len(tool_denom), 1) * 100:.1f}%")
    print(f"  平均步数        {avg_steps:.2f}  (ReAct 样本 {len(step_rows)})")
    print(f"  步数分布        {dict(sorted(dist.items()))}")
    print(f"  停止原因分布    {dict(sorted(stop_dist.items()))}")
    print(f"  耗时            {elapsed:.1f}s   异常 {len(errors)}")
    print("=" * 58)

    # 始终输出 badcase，便于定位
    for r in rows:
        if r["error"]:
            print(f"  ⚠️  {r['q']}  {r['error']}")
    for r in rows:
        if r["routed"] != r["expected"]:
            print(f"  ❌ 路由 [{r['expected']}]→[{r['routed']}] {r['method']}  {r['q']}")
    for r in tool_denom:
        got = r["tools"][0] if r["tools"] else None
        if got != r["expected_tool"]:
            print(f"  🔧 工具 期望[{r['expected_tool']}]→实际[{got}]  {r['q']}")

    floor = 60.0
    return 0 if route_ok / max(total, 1) * 100 >= floor and not errors else 1


if __name__ == "__main__":
    sys.exit(main())

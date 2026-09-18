#!/usr/bin/env python3
"""
stop_on_sufficient ablation —— 证据首步即充足时提前收口，能省多少步？

对比：
    OFF  关闭：即使证据已充足，也让模型自己决定是否再检索
    ON   开启（现默认）：`has_sufficient_evidence` 判定充足后，引擎立即停止循环

指标：
    平均步数        OFF vs ON（步数 ≈ LLM 调用次数）
    停止原因分布
    省步数

口径提醒：
    本脚本用 `react_eval_cases.jsonl` 的 video_qa 用例 + 固定证据 mock
    （`_execute_search_tool` 恒返回充足）。因此 ON 的省步是**上限**：
    真实收益 ≈ P(首步即充足) × 1 步。现默认开启（触发条件为已充足，非无条件截断）；
    绝对质量仍建议连 DB 用真实检索复核。

用法:
    cd ai-end
    python3 scripts/eval_stop_on_sufficient.py            # 真实 LLM（需 DEEPSEEK_API_KEY）
    python3 scripts/eval_stop_on_sufficient.py --offline  # replay 离线（零 token）
    python3 scripts/eval_stop_on_sufficient.py --limit 10
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
CANNED_CHUNKS: List[Dict[str, Any]] = [
    {"video_id": VIDEO_ID, "content": "本视频介绍了 ViewHub 平台的核心功能与使用方式。", "score": 0.82},
    {"video_id": VIDEO_ID, "content": "作者演示了从上传到发布视频的完整流程。", "score": 0.74},
]


def load_cases() -> List[dict]:
    rows = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            row = json.loads(line)
            if row.get("expected") == "video_qa_workflow":
                rows.append(row)
    return rows


def _install_mocks() -> None:
    import app.agents.video_qa_react as vq

    vq._execute_search_tool = (  # type: ignore[assignment]
        lambda session_id, video_id, query, title, tags, top_k: (list(CANNED_CHUNKS), True)
    )


def _configure(live: bool) -> None:
    from app.config import settings

    settings.video_qa_react_enabled = True
    settings.video_qa_react_max_steps = 3
    settings.video_qa_semantic_retry_enabled = False  # 只观察停止策略
    if live:
        settings.demo_mode = False
        settings.llm_replay_enabled = False
    else:
        settings.demo_mode = True


def run_one(tc: dict, stop_on_sufficient: bool, session_id: str) -> Dict[str, Any]:
    from app.agents.video_qa_react import run_video_qa_react_retrieval
    from app.config import settings

    settings.video_qa_react_stop_on_sufficient = stop_on_sufficient
    _k, sufficient, steps, _note, stop = run_video_qa_react_retrieval(
        video_id=tc.get("ctx", {}).get("video_id") or VIDEO_ID,
        question=tc["q"],
        title="ViewHub 平台介绍",
        tags="平台,功能",
        session_id=session_id,
    )
    return {"steps": int(steps), "stop_reason": stop, "sufficient": bool(sufficient)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="replay 离线（默认真实 LLM）")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    live = not args.offline
    cases = load_cases()
    if args.limit:
        cases = cases[: args.limit]

    _install_mocks()
    _configure(live)

    print(f"模式: {'live(真实 LLM)' if live else 'replay(离线)'}   用例: {len(cases)}（video_qa）")

    off_steps: List[int] = []
    on_steps: List[int] = []
    off_dist: Dict[str, int] = defaultdict(int)
    on_dist: Dict[str, int] = defaultdict(int)

    t0 = time.time()
    for i, tc in enumerate(cases, 1):
        off = run_one(tc, False, f"sos_off_{i}")
        on = run_one(tc, True, f"sos_on_{i}")
        off_steps.append(off["steps"])
        on_steps.append(on["steps"])
        off_dist[off["stop_reason"]] += 1
        on_dist[on["stop_reason"]] += 1
        if i % 20 == 0 or i == len(cases):
            print(f"  进度 {i}/{len(cases)}  已用 {time.time() - t0:.0f}s", flush=True)

    n = len(cases)
    avg_off = sum(off_steps) / max(n, 1)
    avg_on = sum(on_steps) / max(n, 1)
    print("=" * 62)
    print("  stop_on_sufficient ablation（video_qa，证据首步即充足）")
    print("=" * 62)
    print(f"  平均步数        OFF {avg_off:.2f}  →  ON {avg_on:.2f}   省 {avg_off - avg_on:.2f} 步/次")
    print(f"  总步数(≈LLM调用) OFF {sum(off_steps)}     →  ON {sum(on_steps)}")
    print(f"  停止原因 OFF    {dict(sorted(off_dist.items()))}")
    print(f"  停止原因 ON     {dict(sorted(on_dist.items()))}")
    print(f"  耗时            {time.time() - t0:.1f}s")
    print("=" * 62)
    print("  注：mock 首步即返回充足，故省步为上限；真实收益 ≈ P(首步充足) × 1 步。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

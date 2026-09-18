#!/usr/bin/env python3
"""
记忆冲突判定（LLM Judge）评测。

对比对象：`similarity()` 阈值（见 eval_memory_supersede.py，同义改写命中 0）vs LLM Judge。
用例同 `fixtures/memory_supersede_cases.jsonl`（dup / para / distinct）。

判定正确标准：
- dup / para  → 期望「不新增」：SUPERSEDE（取代旧的）或 NOOP（已存在）都算对
- distinct    → 期望 ADD（不同偏好，必须新增，不能取代/忽略）

指标：整体准确率 + 分类命中率 + 各分类动作分布。

用法:
    cd ai-end
    python3 scripts/eval_memory_judge.py           # 真实 LLM
    python3 scripts/eval_memory_judge.py --offline  # replay（零 token）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "memory_supersede_cases.jsonl"


def load_cases() -> List[dict]:
    rows = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _configure(live: bool) -> None:
    from app.config import settings

    if live:
        settings.demo_mode = False
        settings.llm_replay_enabled = False
    else:
        settings.demo_mode = True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="replay（零 token）")
    args = parser.parse_args()

    live = not args.offline
    _configure(live)

    from app.agents.memory_judge import judge_memory

    cases = load_cases()
    print(f"模式: {'live(真实 LLM)' if live else 'replay'}   用例: {len(cases)}（dup/para/distinct）")

    per_kind_correct: Dict[str, int] = defaultdict(int)
    per_kind_total: Dict[str, int] = defaultdict(int)
    per_kind_action: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    errors: List[str] = []

    t0 = time.time()
    for i, c in enumerate(cases, 1):
        existing = [{"id": 1, "type": "preference", "content": c["a"]}]
        decision = judge_memory(c["b"], existing, memory_type="preference")
        # dup/para：只要不新增（SUPERSEDE 或 NOOP）就算识别为同一记忆；distinct：必须 ADD
        expect_add = c["kind"] == "distinct"
        correct = (decision.action == "ADD") == expect_add
        per_kind_total[c["kind"]] += 1
        per_kind_action[c["kind"]][decision.action] += 1
        if correct:
            per_kind_correct[c["kind"]] += 1
        elif len(errors) < 12:
            errors.append(f"{c['kind']}: {c['a']} | {c['b']} → {decision.action}")
        if i % 10 == 0 or i == len(cases):
            print(f"  进度 {i}/{len(cases)}  已用 {time.time() - t0:.0f}s", flush=True)

    total = len(cases)
    correct_total = sum(per_kind_correct.values())
    print("=" * 64)
    print("  记忆冲突判定（LLM Judge）评测")
    print("=" * 64)
    print(f"  整体准确率    {correct_total}/{total}   {correct_total / max(total, 1) * 100:.1f}%")
    for kind in ("dup", "para", "distinct"):
        t = per_kind_total[kind]
        c_ = per_kind_correct[kind]
        dist = dict(sorted(per_kind_action[kind].items()))
        print(f"  {kind:9}     {c_}/{t}   {c_ / max(t, 1) * 100:5.1f}%   动作分布 {dist}")
    print(f"  耗时          {time.time() - t0:.1f}s")
    print("=" * 64)
    if errors:
        print("  错例（前 12）:")
        for e in errors:
            print(f"    {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

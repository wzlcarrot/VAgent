#!/usr/bin/env python3
"""构造 SFT 数据：**验证集只用人工标注（golden）**，训练集 = 剩余人工 + LLM 合成。

- 输入：
    fixtures/routing_golden.jsonl      357 例人工标注（q + expected + tier）
    fixtures/routing_augmented.jsonl   LLM 合成（仅用于训练，可选）
- 输出：
    data/finetune/train.jsonl      训练（messages 格式）
    data/finetune/val.jsonl        验证（messages 格式）
    data/finetune/val_labels.jsonl {q, expected, tier, source}
- 划分：验证集从 golden **分层**取（难例优先），保证是**真·held-out 人工标注**；
  合成数据**只进训练集**，不污染验证集。

用法：cd ai-end && python3 scripts/finetune/export_sft.py --val-size 250
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.finetune.common import (  # noqa: E402
    DATA_DIR,
    GOLDEN,
    LABELS,
    messages,
    read_jsonl,
    write_jsonl,
)

AUGMENTED = Path(__file__).resolve().parents[2] / "fixtures" / "routing_augmented.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--val-size", type=int, default=250, help="验证集大小（只用人工标注）")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    golden = read_jsonl(GOLDEN)
    if not golden:
        print(f"找不到数据: {GOLDEN}")
        return 1
    augmented = read_jsonl(AUGMENTED) if AUGMENTED.exists() else []
    print(f"人工标注 {len(golden)} / 合成 {len(augmented)}")

    rng = random.Random(args.seed)
    by_label = defaultdict(list)
    for r in golden:
        by_label[r["expected"]].append(r)

    # 验证集：每类等量，难例（ambiguous/offtopic）优先
    per_label = max(1, args.val_size // len(LABELS))
    _tier_rank = {"ambiguous": 0, "offtopic": 0, "easy": 1}
    val, train_real = [], []
    for label in LABELS:
        items = by_label.get(label, [])
        items = sorted(items, key=lambda r: (_tier_rank.get(r.get("tier", "easy"), 1), rng.random()))
        val.extend(items[:per_label])
        train_real.extend(items[per_label:])

    # 训练集 = 剩余人工 + 全部合成（合成只训练、不验证）
    train = [messages(r["q"], r["expected"]) for r in train_real] + \
            [messages(r["q"], r["expected"]) for r in augmented]
    rng.shuffle(train)

    write_jsonl(DATA_DIR / "train.jsonl", train)
    write_jsonl(DATA_DIR / "val.jsonl", [messages(r["q"], r["expected"]) for r in val])
    write_jsonl(
        DATA_DIR / "val_labels.jsonl",
        [{"q": r["q"], "expected": r["expected"], "tier": r.get("tier", "?"), "source": "human"} for r in val],
    )

    tier_dist: dict = defaultdict(int)
    for r in val:
        tier_dist[r.get("tier", "?")] += 1
    print(f"train {len(train)}（人工 {len(train_real)} + 合成 {len(augmented)}） / val {len(val)}（全部人工）")
    print(f"验证集难度: {dict(tier_dist)}")
    print(f"输出: {DATA_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

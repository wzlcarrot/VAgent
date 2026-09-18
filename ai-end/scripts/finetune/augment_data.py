#!/usr/bin/env python3
"""LLM 合成意图分类训练数据（只扩**训练集**，不污染人工标注的验证集）。

- 每条意图让 LLM 生成 N 个不同说法的问题（口语/简短/稍歧义）
- 去重（精确 + 与既有 golden 重复）后写入 fixtures/routing_augmented.jsonl
- 标记 source=synthetic，便于评测时区分

用法：cd ai-end && python3 scripts/finetune/augment_data.py --per-intent 200
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.finetune.common import GOLDEN, LABELS, read_jsonl  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "fixtures" / "routing_augmented.jsonl"

INTENT_DESC = {
    "video_qa_workflow": "针对**某个具体视频内容**的问答（讲什么、作者、时长、简介、某段内容）",
    "recommend_workflow": "求推荐视频（想要一些视频、换一批、同类推荐、某主题推荐）",
    "user_data_workflow": "查询**用户自己的数据**（收藏、关注、硬币、观看历史、粉丝）",
    "chat_workflow": "平台功能咨询（怎么上传/注册/点赞）或闲聊（你好、谢谢）",
}

_SYS = (
    "你是中文对话数据生成器。为指定意图生成**多样化**的用户问题："
    "覆盖口语化、简短、书面、稍带歧义的说法。只输出 JSON 数组，不要解释。"
)


def gen_batch(label: str, n: int, temperature: float) -> list:
    from app.tools.llm_tools import LLM_tools

    prompt = (
        f"意图：{label}\n含义：{INTENT_DESC[label]}\n"
        f"请生成 {n} 个该意图下的不同用户问题（不要与其他意图混）。"
        f'只输出 JSON 数组，例如 ["问题1","问题2"]。'
    )
    raw = LLM_tools.chat_sync(
        [{"role": "system", "content": _SYS}, {"role": "user", "content": prompt}],
        temperature=temperature, max_tokens=1500,
    ) or ""
    start, end = raw.find("["), raw.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        arr = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return []
    return [str(x).strip() for x in arr if isinstance(x, (str,)) and str(x).strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-intent", type=int, default=200)
    ap.add_argument("--batch", type=int, default=20)
    args = ap.parse_args()

    existing = {r["q"].strip() for r in read_jsonl(GOLDEN)}
    seen = set(existing)
    rows = []
    for label in LABELS:
        got, tries = 0, 0
        while got < args.per_intent and tries < 40:
            tries += 1
            for q in gen_batch(label, min(args.batch, args.per_intent - got), 0.9):
                if q in seen:
                    continue
                seen.add(q)
                rows.append({"q": q, "expected": label, "tier": "synthetic", "source": "synthetic"})
                got += 1
        print(f"  {label}: 生成 {got}")

    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    print(f"共生成 {len(rows)} 条 → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""评测意图分类：基座 vs LoRA adapter（可选对比项目关键词路由）。

- 数据：data/finetune/val_labels.jsonl（{q, expected, tier}）
- 指标：整体准确率 + 按难度分层（easy / ambiguous / offtopic）
- 用法：
    # 只看 LoRA
    python3 scripts/finetune/eval_intent.py --base-model <path> --adapter <path>
    # 对比基座
    python3 scripts/finetune/eval_intent.py --base-model <path>
    # 顺带对比项目关键词路由
    python3 scripts/finetune/eval_intent.py --base-model <path> --adapter <path> --compare-router
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.finetune.common import (  # noqa: E402
    DATA_DIR,
    LABELS,
    SYSTEM_PROMPT,
    read_jsonl,
    render_chat,
)

# few-shot 示例（用于给基座一个公平的 baseline：不是它不会，是没人教它标签）
FEWSHOT = [
    ("这个视频讲了什么", "video_qa_workflow"),
    ("推荐点视频", "recommend_workflow"),
    ("我的收藏有哪些", "user_data_workflow"),
    ("怎么上传视频", "chat_workflow"),
    ("作者是谁", "video_qa_workflow"),
    ("有什么好看的", "recommend_workflow"),
    ("我有多少硬币", "user_data_workflow"),
    ("你好", "chat_workflow"),
]


def build_system_prompt(few_shot: int) -> str:
    if few_shot <= 0:
        return SYSTEM_PROMPT
    examples = FEWSHOT[:few_shot]
    lines = "\n".join(f"问：{q} → 答：{lab}" for q, lab in examples)
    return f"{SYSTEM_PROMPT}\n示例：\n{lines}\n"


def parse_label(text: str) -> str:
    t = (text or "").strip().lower()
    for lab in LABELS:
        if lab in t:
            return lab
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-model", required=True)
    ap.add_argument("--adapter", default="")
    ap.add_argument("--data", default=str(DATA_DIR / "val_labels.jsonl"))
    ap.add_argument("--compare-router", action="store_true")
    ap.add_argument("--max-samples", type=int, default=0)
    ap.add_argument("--few-shot", type=int, default=0, help="给基座塞 N 个示例（公平 baseline）")
    args = ap.parse_args()

    rows = read_jsonl(Path(args.data))
    if args.max_samples:
        rows = rows[: args.max_samples]
    print(f"评测样本 {len(rows)}")

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        device_map="auto" if torch.cuda.is_available() else None,
        trust_remote_code=True,
    )
    if args.adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, args.adapter)
    model.eval()

    sys_prompt = build_system_prompt(args.few_shot)
    hit: dict = defaultdict(int)
    tot: dict = defaultdict(int)
    wrong = []
    for r in rows:
        msgs = [{"role": "system", "content": sys_prompt},
                {"role": "user", "content": r["q"]}]
        prompt = render_chat(tok, msgs, add_generation_prompt=True)
        ids = tok(prompt, return_tensors="pt").to(model.device)
        with torch.no_grad():
            out = model.generate(**ids, max_new_tokens=16, do_sample=False)
        gen = tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
        pred = parse_label(gen)
        tier = r.get("tier", "?")
        tot["all"] += 1
        tot[tier] += 1
        if pred == r["expected"]:
            hit["all"] += 1
            hit[tier] += 1
        elif len(wrong) < 10:
            wrong.append((r["q"], r["expected"], pred))

    print("=" * 50)
    tag = "LoRA" if args.adapter else "基座"
    if args.few_shot:
        tag += f"+few-shot({args.few_shot})"
    print(f"  意图分类准确率（{tag}）")
    print("=" * 50)
    for k in ["all", "easy", "ambiguous", "offtopic"]:
        if tot[k]:
            print(f"  {k:10} {hit[k]}/{tot[k]}  {hit[k] / tot[k] * 100:.1f}%")
    if wrong:
        print("  错例（前 10）:")
        for q, exp, got in wrong:
            print(f"    {q}  期望 {exp}  得到 {got or '（无法解析）'}")

    if args.compare_router:
        from app.agents.router import Router
        r_obj = Router()
        r_hit = r_tot = 0
        for r in rows:
            if r_obj.route(r["q"]) == r["expected"]:
                r_hit += 1
            r_tot += 1
        print("-" * 50)
        print(f"  关键词路由（baseline） {r_hit}/{r_tot}  {r_hit / max(r_tot, 1) * 100:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())

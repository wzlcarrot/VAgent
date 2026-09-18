#!/usr/bin/env python3
"""本地推理：用（基座 + LoRA adapter）预测单条问题的意图。

用法：
    # 基座
    python3 scripts/finetune/predict.py --base-model <path> --question "怎么上传视频"
    # 基座 + LoRA
    python3 scripts/finetune/predict.py --base-model <path> --adapter <path> \
        --question "主题讲的是什么" --question "推荐点视频"
    # 不带 --question 时跑内置示例
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.finetune.common import LABELS, SYSTEM_PROMPT, render_chat  # noqa: E402

DEMO = [
    "这个视频讲了什么",
    "主题讲的是什么",
    "推荐点科幻视频",
    "我收藏了哪些视频",
    "怎么上传视频",
    "你好呀",
]


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
    ap.add_argument("--question", action="append", default=[])
    args = ap.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.base_model, dtype=torch.float32, trust_remote_code=True,
    )
    if args.adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, args.adapter)
    model.eval()

    questions = args.question or DEMO
    tag = "基座+LoRA" if args.adapter else "基座"
    print(f"[{tag}]")
    for q in questions:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": q}]
        prompt = render_chat(tok, msgs, add_generation_prompt=True)
        ids = tok(prompt, return_tensors="pt")
        with torch.no_grad():
            out = model.generate(**ids, max_new_tokens=16, do_sample=False)
        gen = tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
        print(f"  {q}  →  {parse_label(gen) or '（无法解析: ' + gen.strip()[:20] + '）'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

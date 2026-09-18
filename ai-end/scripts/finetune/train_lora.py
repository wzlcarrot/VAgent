#!/usr/bin/env python3
"""LoRA 微调 Qwen 做意图分类。

- 基座：Qwen/Qwen2.5-0.6B-Instruct（可用 --base-model 换）
- 数据：data/finetune/train.jsonl（由 export_sft.py 生成，chat 格式）
- 方法：LoRA（冻结基座，只训低秩矩阵），**只在 assistant 回复上算 loss**
- 产出：LoRA adapter（保存到 --output）

用法（GPU 服务器）：
    python3 scripts/finetune/train_lora.py \
        --base-model /root/autodl-tmp/Qwen2.5-0.6B-Instruct \
        --output /root/autodl-tmp/lora-intent \
        --epochs 3 --max-steps 200

本地校验（不加载模型，只验数据/配置）：
    python3 scripts/finetune/train_lora.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.finetune.common import DATA_DIR, read_jsonl, render_chat  # noqa: E402


def build_example(tok, sample: dict, max_len: int) -> dict:
    """把一条 messages 样本转成 input_ids/labels（**只在 assistant 段算 loss**）。"""
    msgs = sample["messages"]
    prompt_text = render_chat(tok, msgs[:-1], add_generation_prompt=True)
    full_text = render_chat(tok, msgs, add_generation_prompt=False)
    p_ids = tok(prompt_text, add_special_tokens=False)["input_ids"]
    f_ids = tok(full_text, add_special_tokens=False)["input_ids"]
    f_ids = f_ids[:max_len]
    labels = ([ -100 ] * len(p_ids) + f_ids[len(p_ids):])[:max_len]
    return {"input_ids": f_ids, "labels": labels, "attention_mask": [1] * len(f_ids)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-model", default="Qwen/Qwen3-0.6B")
    ap.add_argument("--output", default=str(DATA_DIR / "lora-intent"))
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--max-steps", type=int, default=-1)
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--grad-accum", type=int, default=4)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--max-len", type=int, default=512)
    ap.add_argument("--lora-r", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true", help="只校验数据/配置，不加载模型")
    args = ap.parse_args()

    train_rows = read_jsonl(DATA_DIR / "train.jsonl")
    val_rows = read_jsonl(DATA_DIR / "val.jsonl")
    print(f"训练样本 {len(train_rows)} / 验证样本 {len(val_rows)}")
    if not train_rows:
        print("请先运行 export_sft.py")
        return 1

    if args.dry_run:
        print("[dry-run] 配置:")
        print(f"  base_model={args.base_model}")
        print(f"  output={args.output}")
        print(f"  lora r={args.lora_r} alpha={args.lora_r * 2}")
        print(f"  epochs={args.epochs} batch={args.batch_size} grad_accum={args.grad_accum} lr={args.lr}")
        print("  OK（未加载模型）")
        return 0

    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        DataCollatorForSeq2Seq,
        Trainer,
        TrainingArguments,
    )

    tok = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        device_map="auto" if torch.cuda.is_available() else None,
        trust_remote_code=True,
    )
    model.config.use_cache = False

    lora = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_r * 2,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    train_ds = [build_example(tok, s, args.max_len) for s in train_rows]
    val_ds = [build_example(tok, s, args.max_len) for s in val_rows]

    targs = TrainingArguments(
        output_dir=args.output,
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        logging_steps=10,
        save_strategy="epoch",
        report_to=[],
        fp16=torch.cuda.is_available(),
    )
    collator = DataCollatorForSeq2Seq(tok, padding=True, label_pad_token_id=-100)
    trainer = Trainer(model=model, args=targs, train_dataset=train_ds, eval_dataset=val_ds, data_collator=collator)
    trainer.train()

    Path(args.output).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(args.output)
    tok.save_pretrained(args.output)
    print(f"LoRA adapter 已保存: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

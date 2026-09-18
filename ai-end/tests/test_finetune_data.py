"""微调数据与 label 掩码测试（不需要模型/GPU）。"""
from scripts.finetune.common import LABELS, messages
from scripts.finetune.train_lora import build_example


class _FakeTok:
    """极简假 tokenizer：字符即 token。"""

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=False):
        s = "".join(f"<{m['role']}>{m['content']}" for m in messages)
        if add_generation_prompt:
            s += "<assistant>"
        return s

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": [ord(c) for c in text]}


def test_messages_format():
    m = messages("怎么上传视频", "chat_workflow")
    assert [x["role"] for x in m["messages"]] == ["system", "user", "assistant"]
    assert m["messages"][-1]["content"] in LABELS


def test_label_mask_only_on_assistant():
    sample = {"messages": [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "U"},
        {"role": "assistant", "content": "L"},
    ]}
    ex = build_example(_FakeTok(), sample, max_len=10_000)
    prompt_len = len("<system>S<user>U<assistant>")
    # prompt 段全部 -100（不算 loss）
    assert all(x == -100 for x in ex["labels"][:prompt_len])
    # assistant 段是真实 token（算 loss）
    assert ex["labels"][prompt_len:] == [ord("L")]
    assert len(ex["input_ids"]) == len(ex["labels"]) == len(ex["attention_mask"])


def test_max_len_truncation():
    sample = {"messages": [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "U" * 100},
        {"role": "assistant", "content": "L"},
    ]}
    ex = build_example(_FakeTok(), sample, max_len=20)
    assert len(ex["input_ids"]) <= 20
    assert len(ex["labels"]) <= 20

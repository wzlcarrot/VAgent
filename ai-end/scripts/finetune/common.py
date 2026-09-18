"""微调共用：标签集、系统提示、路径、数据格式。

任务：**意图分类**（question → 4 类之一），与项目关键词路由（80.7%）对比。
"""
from __future__ import annotations

import json
from pathlib import Path

LABELS = [
    "video_qa_workflow",
    "recommend_workflow",
    "user_data_workflow",
    "chat_workflow",
]

SYSTEM_PROMPT = (
    "你是 ViewHub 的意图分类器。把用户问题归为以下之一，只输出标签本身，不要解释：\n"
    "- video_qa_workflow：针对某个具体视频内容的问答\n"
    "- recommend_workflow：求推荐视频\n"
    "- user_data_workflow：查询用户自己的数据（收藏/关注/硬币/历史等）\n"
    "- chat_workflow：平台功能咨询或闲聊\n"
)

ROOT = Path(__file__).resolve().parents[2]          # ai-end/
GOLDEN = ROOT / "fixtures" / "routing_golden.jsonl"
DATA_DIR = ROOT / "data" / "finetune"


def render_chat(tok, msgs: list, add_generation_prompt: bool) -> str:
    """渲染 chat 模板。Qwen3 默认开启 thinking，会干扰分类 → 显式关闭。

    对不支持 `enable_thinking` 的模板（如 Qwen2.5）自动回退。
    """
    try:
        return tok.apply_chat_template(
            msgs, tokenize=False, add_generation_prompt=add_generation_prompt,
            enable_thinking=False,
        )
    except TypeError:
        return tok.apply_chat_template(
            msgs, tokenize=False, add_generation_prompt=add_generation_prompt,
        )


def messages(question: str, label: str) -> dict:
    """训练用样本（chat 格式）。"""
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
            {"role": "assistant", "content": label},
        ]
    }


def write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

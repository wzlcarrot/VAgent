"""微调意图分类模型（Qwen3-0.6B + LoRA）接入路由。

- **懒加载**：首次调用才载入（1.2G），未配置/加载失败 → 静默返回 None，不影响主流程
- 模型输出标签 **即 workflow_type 字符串**，直接映射
- 支持"合并后的完整模型"目录（基座+LoRA）

⚠️ 生产建议把分类模型单独部署成服务；本项目内置是为了演示"项目能用微调模型"。
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from app.agents.workflows.constants import WorkflowType
from app.config import settings

logger = logging.getLogger(__name__)

_LABELS = [
    WorkflowType.VIDEO_QA,
    WorkflowType.RECOMMEND,
    WorkflowType.USER_DATA,
    WorkflowType.CHAT,
]

_SYSTEM = (
    "你是 ViewHub 的意图分类器。把用户问题归为以下之一，只输出标签本身，不要解释：\n"
    "- video_qa_workflow：针对某个具体视频内容的问答\n"
    "- recommend_workflow：求推荐视频\n"
    "- user_data_workflow：查询用户自己的数据（收藏/关注/硬币/历史等）\n"
    "- chat_workflow：平台功能咨询或闲聊\n"
)

_lock = threading.Lock()
_loaded = False
_model = None
_tok = None


def _try_load() -> None:
    global _loaded, _model, _tok
    if _loaded:
        return
    with _lock:
        if _loaded:
            return
        _loaded = True
        path = settings.finetune_intent_model_path
        if not settings.finetune_intent_enabled or not path:
            logger.info("finetune intent 未启用或未配置路径")
            return
        if not Path(path).exists():
            logger.warning("finetune intent 模型路径不存在: %s", path)
            return
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            _tok = AutoTokenizer.from_pretrained(str(path), trust_remote_code=True)
            _model = AutoModelForCausalLM.from_pretrained(
                str(path), dtype=torch.float32, trust_remote_code=True,
            )
            _model.eval()
            logger.info("finetune intent 模型已加载: %s", path)
        except Exception as e:  # noqa: BLE001
            logger.warning("finetune intent 模型加载失败: %s", e)
            _model = None
            _tok = None


def is_available() -> bool:
    if not settings.finetune_intent_enabled:
        return False
    _try_load()
    return _model is not None and _tok is not None


def _render(msgs: list, add_generation_prompt: bool) -> str:
    try:
        return _tok.apply_chat_template(
            msgs, tokenize=False, add_generation_prompt=add_generation_prompt,
            enable_thinking=False,
        )
    except TypeError:
        return _tok.apply_chat_template(
            msgs, tokenize=False, add_generation_prompt=add_generation_prompt,
        )


def classify(question: str) -> Optional[str]:
    """返回 workflow_type；不可用/无法解析 → None（调用方回退）。"""
    if not question or not is_available():
        return None
    try:
        import torch

        msgs = [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": question}]
        prompt = _render(msgs, add_generation_prompt=True)
        ids = _tok(prompt, return_tensors="pt")
        with torch.no_grad():
            out = _model.generate(
                **ids, max_new_tokens=settings.finetune_intent_max_new_tokens, do_sample=False,
            )
        gen = _tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
        t = gen.strip().lower()
        for lab in _LABELS:
            if lab in t:
                return lab
        return None
    except Exception as e:  # noqa: BLE001
        logger.debug("finetune intent classify 失败: %s", e)
        return None

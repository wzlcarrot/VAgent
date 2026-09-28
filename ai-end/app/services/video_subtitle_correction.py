"""ASR 字幕后处理：结合整段剧情做语义校对（不更换 ASR 模型）。

思路（对应用户反馈）：先通读整段字幕理解剧情，再逐行判断哪些条目语义不通/听错，
按上下文与剧情改写成合理表达，同时把繁体统一成简体。

- 只改文字，不改时间轴与段落数量；
- 失败或 LLM 不可用时回退原文，保证主流程不受影响；
- 长度突变视为不可靠，保留原文，避免模型扩写/幻觉。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "你是中文短视频字幕的语义校对员。用户会按时间顺序给出某视频的完整 ASR 字幕，"
    "其中可能存在同音字、听错的词、语义不通的碎片，以及繁体字。\n"
    "请这样处理：\n"
    "1) 先通读全篇，理解整段剧情和说话人；\n"
    "2) 再逐行判断：只要某行语义不通、或明显是听错的词，就结合上下文与剧情，"
    "改成合理、自然、符合剧情的简体中文；通顺正确的行保持原样；\n"
    "3) 繁体一律转成简体；\n"
    "4) 不增删行、不合并或拆分、保持行数与顺序完全一致。\n"
    '只输出 JSON，格式：{"lines":["第一行","第二行","..."]}。'
)


def _to_simplified(text: str) -> str:
    """繁体转简体；zhconv 不可用时原样返回。"""
    if not text:
        return text
    try:
        from zhconv import convert  # type: ignore
        return convert(text, "zh-cn")
    except Exception:
        return text


def _extra_payload() -> Optional[Dict[str, Any]]:
    """DeepSeek：关闭思考避免 reasoning 占满 max_tokens；可指定更强模型与 effort。"""
    prov = (settings.llm_provider or "").lower()
    extra: Dict[str, Any] = {}
    if "deepseek" in prov:
        extra["thinking"] = {"type": "disabled"}
        model = (getattr(settings, "video_asr_correct_model", "") or "").strip()
        effort = (getattr(settings, "video_asr_correct_effort", "") or "").strip()
        if model:
            extra["model"] = model
        if effort:
            extra["effort"] = effort
    return extra or None


def _batch(segments: List[Dict[str, Any]], max_items: int, max_chars: int) -> List[List[int]]:
    """按条数与字符数切分下标，控制单次请求体量。"""
    batches: List[List[int]] = []
    cur: List[int] = []
    cur_chars = 0
    for i, seg in enumerate(segments):
        text = str(seg.get("text") or "")
        if cur and (len(cur) >= max_items or cur_chars + len(text) > max_chars):
            batches.append(cur)
            cur, cur_chars = [], 0
        cur.append(i)
        cur_chars += len(text)
    if cur:
        batches.append(cur)
    return batches


def _accept_or_keep(original: str, corrected: str) -> str:
    """保守校验：长度突变视为不可靠，保留原文。"""
    o = original.strip()
    c = (corrected or "").strip()
    if not c:
        return o
    if len(c) > max(4, int(len(o) * 2.0)):
        return o
    if len(c) < max(1, int(len(o) * 0.4)):
        return o
    return c


def correct_segments(
    segments: List[Dict[str, Any]], context: str = ""
) -> List[Dict[str, Any]]:
    """
    对 ASR 段做「整段语义校对」，返回新列表（仅 text 可能变化，时间轴/顺序保持）。
    """
    if not segments or not settings.video_asr_correct_enabled:
        return segments

    try:
        from app.tools.llm_tools import LLM_tools
    except Exception as e:  # pragma: no cover
        logger.warning("纠错跳过：LLM_tools 不可用 %s", e)
        return segments

    out = [dict(seg) for seg in segments]
    context_block = (context or "").strip()
    batches = _batch(
        out,
        max_items=settings.video_asr_correct_batch_size,
        max_chars=settings.video_asr_correct_max_chars,
    )
    changed = 0
    for idxs in batches:
        lines = [str(out[i].get("text") or "").strip() for i in idxs]
        user_prompt = ""
        if context_block:
            user_prompt += context_block + "\n\n"
        user_prompt += f"字幕（按顺序，共 {len(lines)} 行）：\n" + "\n".join(lines)
        try:
            data = LLM_tools.chat_sync_json(
                [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=settings.video_asr_correct_max_tokens,
                timeout=settings.video_asr_correct_timeout_s,
                extra_payload=_extra_payload(),
            )
        except Exception as e:
            logger.warning("纠错批次调用失败，保留原文: %s", e)
            continue

        arr = data.get("lines") if isinstance(data, dict) else None
        if not isinstance(arr, list) or len(arr) != len(idxs):
            # 行数不一致视为不可靠，仅做繁转简兜底
            for i in idxs:
                original = str(out[i].get("text") or "")
                simplified = _to_simplified(original)
                if simplified != original:
                    out[i]["text"] = simplified
                    changed += 1
            continue
        for pos, i in enumerate(idxs):
            original = str(out[i].get("text") or "")
            candidate = _accept_or_keep(original, str(arr[pos] or ""))
            simplified = _to_simplified(candidate)
            if simplified != original:
                out[i]["text"] = simplified
                changed += 1

    logger.info("ASR 纠错完成 segments=%d changed=%d", len(out), changed)
    return out

"""从用户问题里抽出 video_id，并去掉检索噪声。"""
from __future__ import annotations

import re
from typing import Optional

# 只用 ASCII：Python 的 \w 会吞掉后面的中文
_ID_CHARS = r"[A-Za-z0-9_-]"
_VIDEO_ID_PATTERNS = (
    re.compile(rf"video[_-]?\s?id[号是:：\s]*({_ID_CHARS}+)", re.I),
    re.compile(rf"视频\s*id[号是:：\s]*({_ID_CHARS}+)", re.I),
    re.compile(rf"\bid[号是:：\s]*({_ID_CHARS}+)", re.I),
)

_VIDEO_ID_NOISE = re.compile(
    rf"(?:video[_-]?\s?id|视频\s*id|\bid)[号是:：\s]*{_ID_CHARS}{{4,}}",
    re.I,
)


def extract_video_id_from_text(text: str) -> Optional[str]:
    """从「video_id:xxx / id号是xxx / 视频id：xxx」中抽出 ID。"""
    raw = (text or "").strip()
    if not raw:
        return None
    for pat in _VIDEO_ID_PATTERNS:
        m = pat.search(raw)
        if m and m.group(1) and len(m.group(1)) >= 4:
            return m.group(1)
    return None


def strip_video_id_noise(text: str) -> str:
    """检索前去掉 video_id 字面量，避免污染 embedding / BM25。"""
    cleaned = _VIDEO_ID_NOISE.sub(" ", text or "")
    return re.sub(r"\s+", " ", cleaned).strip()

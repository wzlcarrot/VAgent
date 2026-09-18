"""查询归一化：把"等价写法"映射到同一个缓存 key，提升命中率。

分两级：
- `normalize_text`：表层归一（去空白/标点、转小写）——安全，只是清理噪声
- `normalize_query`：表层 + 同义词替换——把"如何/咋/怎样"统一成"怎么"

注意：归一化只能处理**表层差异**；语序不同（"视频如何上传" vs "怎么上传视频"）
与换说法要靠**语义缓存**（embedding 相似度），不在本模块范围。
"""
from __future__ import annotations

import re

# 常见中英文标点 + 空白
_PUNCT_RE = re.compile(
    r"[\s\u3000"
    r"，。！？、；：“”‘’（）【】《》〈〉…—·～「」『』"
    r"!?.,;:\"'()\[\]{}<>/\\|~`@#$%^&*+=_-]+"
)

# 同义词/口语归一（按 key 长度降序替换，避免"怎么样"被"怎样"截断）
_SYNONYMS = {
    "怎么样": "怎么",
    "怎样": "怎么",
    "如何": "怎么",
    "咋样": "怎么",
    "咋": "怎么",
    "啥": "什么",
    "介绍一下": "介绍",
    "介绍下": "介绍",
}


def normalize_text(text: str) -> str:
    """表层归一：去空白/标点、转小写。"""
    if not text:
        return ""
    return _PUNCT_RE.sub("", str(text).strip().lower())


def normalize_query(text: str) -> str:
    """查询归一：表层 + 同义词替换（用于路由等"粗决策"缓存 key）。"""
    s = normalize_text(text)
    for key in sorted(_SYNONYMS, key=len, reverse=True):
        s = s.replace(key, _SYNONYMS[key])
    return s

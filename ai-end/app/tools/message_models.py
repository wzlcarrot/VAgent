"""
结构化消息模型

方案 A：仅在 compact 与 token 估算层内部使用。
Redis 存储与 API 传输仍用 dict（JSON），通过 to_dict / from_dict 边界转换，
避免牵连 chat.py / chat_graph 的 dict 处理链路。

关键改进：compact boundary/summary 等内部消息用 is_internal 结构化标记，
替代原先拼在 content 里的字符串 flag（__compact_boundary__ / __compact_summary__）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Union

# 兼容旧数据的字符串 flag（旧 Redis 消息仍用字符串标记）
COMPACT_BOUNDARY_FLAG = "__compact_boundary__"
COMPACT_SUMMARY_FLAG = "__compact_summary__"

Content = Union[str, List[Dict[str, Any]]]


@dataclass
class Message:
    """会话消息。is_internal 标记内部消息（compact boundary/summary），不参与 LLM 输入。"""

    role: str
    content: Content
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    is_internal: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "role": self.role,
            "content": self.content,
        }
        if self.timestamp:
            d["timestamp"] = self.timestamp
        if self.is_internal:
            d["is_internal"] = True
        return d

    def to_json(self) -> str:
        """序列化为 Redis 存储用的 JSON 字符串（ensure_ascii=False 兼容中文）。"""
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Message":
        return cls(
            role=d.get("role", ""),
            content=d.get("content", ""),
            timestamp=d.get("timestamp", ""),
            is_internal=bool(d.get("is_internal", False)),
        )

    @classmethod
    def from_json(cls, raw: str) -> "Message":
        try:
            return cls.from_dict(json.loads(raw))
        except (json.JSONDecodeError, TypeError, ValueError):
            return cls(role="unknown", content="")

    # ─── 兼容旧字符串 flag 的内部消息识别 ───
    @property
    def is_compact_boundary(self) -> bool:
        """是否 compact boundary：is_internal 字段 或 旧字符串 flag。"""
        if self.is_internal:
            return True
        return isinstance(self.content, str) and COMPACT_BOUNDARY_FLAG in self.content

    @property
    def is_compact_summary(self) -> bool:
        """是否 compact summary：is_internal 字段 或 旧字符串 flag。"""
        if self.is_internal:
            return True
        return isinstance(self.content, str) and COMPACT_SUMMARY_FLAG in self.content

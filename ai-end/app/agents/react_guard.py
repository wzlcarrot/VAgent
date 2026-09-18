"""ReAct 循环防护：检测重复工具调用，打破无限循环。

max_steps 与 Tool Governor 是兜底（到达上限才停）；当模型反复用**相同参数**
调用**同一个工具**时，结果往往一模一样，继续执行只会浪费 LLM 调用与工具配额。
本模块在每次执行前做去重判断，命中即由调用方提前终止循环。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def normalize_args(args: Optional[Dict[str, Any]]) -> str:
    """把工具参数规范化为稳定字符串，用于重复检测。

    - 字典按键排序，消除 JSON 字段顺序差异
    - 字符串值去首尾空白，避免 ``"q"`` 与 ``"q "`` 被判为不同调用
    - 无法序列化时退化为 ``repr``，保证不抛异常
    """
    if not args:
        return "{}"

    def _norm(value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            return {k: _norm(v) for k, v in sorted(value.items())}
        if isinstance(value, (list, tuple)):
            return [_norm(v) for v in value]
        return value

    try:
        return json.dumps(_norm(args), ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return repr(args)


class DuplicateCallGuard:
    """记录已执行的 ``(工具, 参数)`` 组合，识别重复调用。"""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def is_duplicate(self, tool_name: str, args: Optional[Dict[str, Any]]) -> bool:
        """True = 该调用与本次循环中此前的某次完全相同，不应再执行。"""
        key = f"{tool_name}:{normalize_args(args)}"
        if key in self._seen:
            logger.info("react guard: duplicate tool call detected tool=%s", tool_name)
            return True
        self._seen.add(key)
        return False

    def __len__(self) -> int:
        return len(self._seen)

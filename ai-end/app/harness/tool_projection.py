"""工具结果投影：只截断给模型看的内容，保留结构化字段。

截断策略（借鉴 pi/Claude Code）：
- `keep="head"`（默认）：保留前 N（适合文件/列表，从头看）
- `keep="tail"`：保留后 N（适合命令输出，报错/结果在末尾）
被截断时**加提示**，并可配合 `tool_governor` 的落盘，把完整输出路径告诉模型。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List


def project_tool_result(result: Any, max_chars: int, keep: str = "head") -> Any:
    if max_chars <= 0 or result is None:
        return result
    if isinstance(result, str):
        if len(result) <= max_chars:
            return result
        budget = max(1, max_chars - 13)  # 给 "…[truncated]" 留位置
        if keep == "tail":
            return "…[truncated]\n" + result[-budget:]
        return result[:budget] + "\n…[truncated]"
    if isinstance(result, list):
        return _project_list(result, max_chars, keep)
    if isinstance(result, dict):
        return _project_dict(result, max_chars, keep)
    return result


def _project_list(items: List[Any], max_chars: int, keep: str = "head") -> List[Any]:
    # 未截断时返回**原对象**（供调用方用 `is not` 判断有没有截断）
    seq = list(reversed(items)) if keep == "tail" else list(items)
    out: List[Any] = []
    used = 2  # []
    for item in seq:
        projected = project_tool_result(item, max(64, max_chars - used), keep)
        chunk = json.dumps(projected, ensure_ascii=False, default=str)
        if used + len(chunk) > max_chars and out:
            marker = {"truncated": True, "remaining": len(items) - len(out)}
            if keep == "tail":
                return [marker] + list(reversed(out))
            return out + [marker]
        out.append(projected)
        used += len(chunk) + 1
    if keep == "tail":
        out = list(reversed(out))
    return out if len(out) < len(items) else items


def _project_dict(doc: Dict[str, Any], max_chars: int, keep: str = "head") -> Dict[str, Any]:
    for key in ("content", "block_content", "snippet", "text", "summary"):
        val = doc.get(key)
        if isinstance(val, str) and len(val) > max_chars:
            budget = max(1, max_chars - 13)
            out = dict(doc)
            if keep == "tail":
                out[key] = "…[truncated]\n" + val[-budget:]
            else:
                out[key] = val[:budget] + "\n…[truncated]"
            out["_truncated"] = True
            return out
    return doc


def attach_spill_notice(projected: Any, spill_path: str) -> Any:
    """把"完整输出已存"的提示附到任意类型的结果上（字符串/列表/字典通用）。"""
    if not spill_path:
        return projected
    notice = f"…[完整输出已存: {spill_path}]"
    if isinstance(projected, str):
        return f"{projected}\n{notice}"
    if isinstance(projected, list):
        return list(projected) + [{"_full_output": spill_path}]
    if isinstance(projected, dict):
        return {**projected, "_full_output": spill_path}
    return projected


def inject_tenant_args(
    arguments: Dict[str, Any],
    *,
    user_id: str = "",
    force_user_id: bool = True,
) -> Dict[str, Any]:
    """强制注入租户/用户上下文，防止工具漏传越权。"""
    args = dict(arguments or {})
    if force_user_id and user_id:
        args["user_id"] = user_id
    return args

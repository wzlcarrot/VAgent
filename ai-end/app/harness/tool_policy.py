"""
声明式 Tool Policy —— 按 workflow + tool 配置 allow / forbidden / ask / 限流 / 超时 / 结果截断
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_POLICY_CACHE: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class ToolPolicyRule:
    max_calls: int
    timeout_seconds: float
    decision: str  # allow | forbidden | ask
    max_result_chars: int = 4000
    inject_user_id: bool = False
    # 参数级规则（借鉴 Codex execpolicy）：[{match: {arg: pattern}, decision}]
    # pattern 支持尾部 * 前缀匹配；按顺序首个命中生效
    arg_rules: tuple = ()


def _policy_path() -> Path:
    return Path(__file__).resolve().parents[2] / "policies" / "tool_policy.json"


def load_policy(force: bool = False) -> Dict[str, Any]:
    global _POLICY_CACHE
    if _POLICY_CACHE is not None and not force:
        return _POLICY_CACHE
    path = _policy_path()
    if not path.exists():
        logger.warning(f"tool policy not found: {path}, using empty policy")
        _POLICY_CACHE = {"global": {"default": {}}, "workflows": {}}
        return _POLICY_CACHE
    with open(path, encoding="utf-8") as f:
        _POLICY_CACHE = json.load(f)
    return _POLICY_CACHE


def resolve_rule(agent: str, tool_name: str) -> ToolPolicyRule:
    policy = load_policy()
    wf_rules = (policy.get("workflows") or {}).get(agent) or {}
    global_default = (policy.get("global") or {}).get("default") or {}
    tool_rule = wf_rules.get(tool_name) or global_default

    raw_rules = tool_rule.get("rules") or global_default.get("rules") or []
    arg_rules = tuple(
        (dict(r.get("match") or {}), str(r.get("decision", "allow")))
        for r in raw_rules
        if isinstance(r, dict) and r.get("match")
    )

    return ToolPolicyRule(
        max_calls=int(tool_rule.get("max_calls", global_default.get("max_calls", 10))),
        timeout_seconds=float(tool_rule.get("timeout_seconds", global_default.get("timeout_seconds", 30.0))),
        decision=str(tool_rule.get("decision", global_default.get("decision", "allow"))),
        max_result_chars=int(tool_rule.get("max_result_chars", global_default.get("max_result_chars", 4000))),
        inject_user_id=bool(tool_rule.get("inject_user_id", global_default.get("inject_user_id", False))),
        arg_rules=arg_rules,
    )


def _match_one(value: Any, pattern: Any) -> bool:
    """单条件匹配。

    - 字符串：精确匹配，尾部 `*` 为前缀匹配
    - 字典（类型化谓词，借鉴 Codex execpolicy）：`{"gte": n}` / `{"lte": n}` / `{"regex": r}`
    """
    if isinstance(pattern, dict):
        if "gte" in pattern:
            try:
                if float(value) < float(pattern["gte"]):
                    return False
            except (TypeError, ValueError):
                return False
        if "lte" in pattern:
            try:
                if float(value) > float(pattern["lte"]):
                    return False
            except (TypeError, ValueError):
                return False
        if "regex" in pattern:
            import re
            if not re.search(str(pattern["regex"]), str(value)):
                return False
        return True
    pat = str(pattern)
    text = str(value)
    if pat.endswith("*"):
        return text.startswith(pat[:-1])
    return text == pat


def _match_args(match: Dict[str, Any], arguments: Optional[Dict[str, Any]]) -> bool:
    """所有 match 条件都满足才算命中。"""
    args = arguments or {}
    for key, pattern in match.items():
        if not _match_one(args.get(key, ""), pattern):
            return False
    return True


def effective_decision(rule: ToolPolicyRule, arguments: Optional[Dict[str, Any]] = None) -> str:
    """在基础 decision 上应用参数级规则（首个命中生效）。"""
    for match, decision in rule.arg_rules:
        if _match_args(match, arguments):
            return decision
    return rule.decision

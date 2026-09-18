#!/usr/bin/env python3
"""将 weekly golden 负反馈候选并入 behavior 扩展集。

流程:
  1. 用户点 👎 → data/weekly_golden/{week}.jsonl
  2. 本脚本 --dry-run 审阅负样本
  3. --apply 写入 fixtures/behavior_promoted.json（behavior_golden_set 自动加载）
  4. 人工确认 expected workflow 后跑 behavior_golden_set

用法:
  cd ai-end && python3 scripts/promote_weekly_golden.py --dry-run
  cd ai-end && python3 scripts/promote_weekly_golden.py --apply --week 2026-W36
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.workflows.constants import WorkflowType  # noqa: E402
from app.harness.weekly_golden import list_weekly_cases  # noqa: E402

PROMOTED_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "behavior_promoted.json"

# 粗粒度意图猜测（仅作候选标注，apply 后仍可手改）
_GUESS_RULES = [
    (WorkflowType.RECOMMEND, ("推荐", "好看", "热门", "找两", "看点")),
    (WorkflowType.USER_DATA, ("硬币", "点赞", "收藏", "播放历史", "关注")),
    (WorkflowType.VIDEO_QA, ("这个视频", "讲了什么", "总结", "片里", "这期", "视频里")),
    (WorkflowType.CHAT, ("平台", "功能", "注册", "怎么用", "你好")),
]


def guess_expected(question: str, workflow_type: str = "") -> str:
    if workflow_type in {
        WorkflowType.VIDEO_QA,
        WorkflowType.RECOMMEND,
        WorkflowType.USER_DATA,
        WorkflowType.CHAT,
    }:
        return workflow_type
    for wf, keys in _GUESS_RULES:
        if any(k in question for k in keys):
            return wf
    return WorkflowType.CHAT


def load_promoted() -> list[dict]:
    if not PROMOTED_PATH.exists():
        return []
    data = json.loads(PROMOTED_PATH.read_text(encoding="utf-8"))
    return list(data.get("cases") or [])


def save_promoted(cases: list[dict]) -> None:
    PROMOTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "description": "从 weekly golden 负反馈提升的行为回归用例；人工可改 expected",
        "cases": cases,
    }
    PROMOTED_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def candidates_from_week(week: str | None, limit: int) -> list[dict]:
    data = list_weekly_cases(week, limit=limit)
    out = []
    for c in data.get("cases") or []:
        if c.get("polarity") != "negative":
            continue
        q = (c.get("question") or "").strip()
        if len(q) < 2:
            continue
        out.append({
            "q": q,
            "expected": guess_expected(q, c.get("workflow_type") or ""),
            "ctx": {},
            "source": "weekly_golden",
            "week": c.get("week") or data.get("week"),
            "session_id": c.get("session_id") or "",
            "feedback": c.get("feedback"),
        })
    return out


def dedupe(existing: list[dict], incoming: list[dict]) -> list[dict]:
    seen = {str(x.get("q") or "").strip() for x in existing}
    added = []
    for c in incoming:
        q = c["q"]
        if q in seen:
            continue
        seen.add(q)
        added.append(c)
    return added


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--week", default="", help="ISO 周，如 2026-W36；默认本周")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true", help="只打印候选，不写文件")
    parser.add_argument("--apply", action="store_true", help="写入 fixtures/behavior_promoted.json")
    args = parser.parse_args()
    if not args.dry_run and not args.apply:
        args.dry_run = True

    week = args.week.strip() or None
    incoming = candidates_from_week(week, args.limit)
    existing = load_promoted()
    added = dedupe(existing, incoming)

    print(f"week={week or 'current'} negative_candidates={len(incoming)} new={len(added)} existing={len(existing)}")
    for c in added:
        print(f"  + [{c['expected']}] {c['q']!r}  (week={c.get('week')})")
    if not added:
        print("nothing to promote")
        return 0
    if args.apply:
        merged = existing + added
        save_promoted(merged)
        print(f"wrote {PROMOTED_PATH} total={len(merged)}")
        print("next: 人工校对 expected → python3 scripts/behavior_golden_set.py")
    else:
        print("dry-run only; re-run with --apply to write fixtures/behavior_promoted.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

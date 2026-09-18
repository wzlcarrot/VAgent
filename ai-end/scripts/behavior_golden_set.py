#!/usr/bin/env python3
"""
Behavior Golden Set —— 路由 + 指代消解 + Tool Policy 行为评测。

用法:
  cd ai-end && python3 scripts/behavior_golden_set.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.router import Router  # noqa: E402
from app.agents.workflows.constants import WorkflowType  # noqa: E402
from app.conversation.context_manager import resolve_references, update_recommendations  # noqa: E402
from app.harness.tool_policy import resolve_rule  # noqa: E402

VIDEO_ID = "v_demo_001"
PROMOTED_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "behavior_promoted.json"


def _load_promoted_cases() -> list[tuple]:
    """加载 fixtures/behavior_promoted.json（由 promote_weekly_golden.py 写入）。"""
    if not PROMOTED_PATH.exists():
        return []
    try:
        data = json.loads(PROMOTED_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = []
    for c in data.get("cases") or []:
        q = (c.get("q") or "").strip()
        expected = c.get("expected")
        if not q or not expected:
            continue
        ctx = c.get("ctx") or {}
        if expected == WorkflowType.VIDEO_QA and "video_id" not in ctx:
            ctx = {**ctx, "video_id": VIDEO_ID}
        if expected in (WorkflowType.RECOMMEND, WorkflowType.USER_DATA) and "user_id" not in ctx:
            ctx = {**ctx, "user_id": "u1"}
        rows.append((q, ctx, expected))
    return rows


def eval_routing() -> tuple[int, int]:
    router = Router()
    cases = [
        ("这个视频讲了什么", {"video_id": VIDEO_ID}, WorkflowType.VIDEO_QA),
        ("视频里讲了啥", {"video_id": VIDEO_ID}, WorkflowType.VIDEO_QA),
        ("推荐一些科技视频", {"user_id": "u1"}, WorkflowType.RECOMMEND),
        ("有什么好看的", {"user_id": "u1"}, WorkflowType.RECOMMEND),
        ("我今天点赞了多少", {"user_id": "u1"}, WorkflowType.USER_DATA),
        ("我的硬币有多少", {"user_id": "u1"}, WorkflowType.USER_DATA),
        ("我关注的up主有哪些", {"user_id": "u1"}, WorkflowType.USER_DATA),
        ("我的播放历史", {"user_id": "u1"}, WorkflowType.USER_DATA),
        ("平台有什么功能", {}, WorkflowType.CHAT),
        ("怎么注册账号", {}, WorkflowType.CHAT),
        ("这个视频有没有类似的", {"video_id": VIDEO_ID, "user_id": "u1"}, WorkflowType.VIDEO_QA),
    ]
    cases = cases + _load_promoted_cases()
    ok = 0
    for q, ctx, expected in cases:
        got = router.hybrid_route(q, ctx)
        if got == expected:
            ok += 1
        else:
            print(f"  ✗ route: {q!r} → {got} (expected {expected})")
    return ok, len(cases)


def eval_reference() -> tuple[int, int]:
    session_id = "behavior-golden-ref"
    recs = [
        {"video_id": "v1", "title": "A"},
        {"video_id": "v2", "title": "B"},
        {"video_id": "v3", "title": "C"},
    ]
    update_recommendations(session_id, recs)
    cases = [
        ("第二个视频讲了什么", "v2"),
        ("第一个呢", "v1"),
        ("第三个讲什么", "v3"),
    ]
    ok = 0
    for q, expected_vid in cases:
        result = resolve_references(session_id, q)
        vid = (result.get("referenced_video") or {}).get("video_id")
        if vid == expected_vid:
            ok += 1
        else:
            print(f"  ✗ ref: {q!r} → {vid} (expected {expected_vid})")
    return ok, len(cases)


def eval_tool_policy() -> tuple[int, int]:
    cases = [
        (WorkflowType.USER_DATA, "vector_search", "forbidden"),
        (WorkflowType.USER_DATA, "user_data_query", "allow"),
        (WorkflowType.VIDEO_QA, "vector_search", "allow"),
        (WorkflowType.VIDEO_QA, "search_video_chunks", "allow"),
        (WorkflowType.RECOMMEND, "retrieve_knowledge", "forbidden"),
        (WorkflowType.RECOMMEND, "recommend_videos", "ask"),
        (WorkflowType.CHAT, "search_video_chunks", "forbidden"),
        (WorkflowType.CHAT, "retrieve_knowledge", "allow"),
    ]
    ok = 0
    for agent, tool, expected in cases:
        rule = resolve_rule(agent, tool)
        if rule.decision == expected:
            ok += 1
        else:
            print(f"  ✗ policy: {agent}/{tool} → {rule.decision} (expected {expected})")
    return ok, len(cases)


def main():
    sections = [
        ("路由", eval_routing),
        ("指代消解", eval_reference),
        ("Tool Policy", eval_tool_policy),
    ]
    total_ok = 0
    total = 0
    print("Behavior Golden Set")
    print("-" * 40)
    for name, fn in sections:
        ok, n = fn()
        total_ok += ok
        total += n
        print(f"{name}: {ok}/{n}")
    print("-" * 40)
    pct = (total_ok / total * 100) if total else 0
    print(f"总计: {total_ok}/{total} ({pct:.0f}%)")
    sys.exit(0 if total_ok == total else 1)


if __name__ == "__main__":
    main()

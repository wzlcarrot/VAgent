"""意图三分路由回归剧本：qa / recommend / chitchat（+ user_data 对照）。

默认用关键词路径（离线稳定、不烧 LLM）；CLI 可用 --fused 跑融合主路径。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.agents.router import Router
from app.agents.workflows.constants import WorkflowType

VIDEO_ID = "video_demo_001"
USER_ID = "u_ternary"

# 用例刻意覆盖「三分意图」的稳定关键词形态；歧义句留给 golden_set 大盘。
TERNARY_CASES: List[dict] = [
    # ── qa（避开 video_exclude 里的「是什么」等）──
    {"bucket": "qa", "q": "这个视频讲了什么", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA},
    {"bucket": "qa", "q": "帮我总结这个视频", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA},
    {"bucket": "qa", "q": "这个视频的作者是谁", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA},
    {"bucket": "qa", "q": "视频里说了什么", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA},
    {"bucket": "qa", "q": "讲解一下这个视频的内容", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA},
    {"bucket": "qa", "q": "这个视频讲得怎么样", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA},
    # ── recommend ──
    {"bucket": "recommend", "q": "推荐一些好看的视频", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.RECOMMEND},
    {"bucket": "recommend", "q": "有什么推荐的", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.RECOMMEND},
    {"bucket": "recommend", "q": "热门视频有哪些", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.RECOMMEND},
    {"bucket": "recommend", "q": "有什么好看的视频", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.RECOMMEND},
    {"bucket": "recommend", "q": "推荐几个视频看看", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.RECOMMEND},
    {"bucket": "recommend", "q": "有什么新出的视频", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.RECOMMEND},
    # ── chitchat ──
    {"bucket": "chitchat", "q": "你们平台有什么功能", "ctx": {}, "expected": WorkflowType.CHAT},
    {"bucket": "chitchat", "q": "怎么使用这个平台", "ctx": {}, "expected": WorkflowType.CHAT},
    {"bucket": "chitchat", "q": "怎么注册账号", "ctx": {}, "expected": WorkflowType.CHAT},
    {"bucket": "chitchat", "q": "这个助手能做什么", "ctx": {}, "expected": WorkflowType.CHAT},
    {"bucket": "chitchat", "q": "帮我介绍一下平台功能", "ctx": {}, "expected": WorkflowType.CHAT},
    {"bucket": "chitchat", "q": "如何上传视频", "ctx": {}, "expected": WorkflowType.CHAT},
    # ── user_data（避开会触发 video 关键词的 up主）──
    {"bucket": "user_data", "q": "我的硬币有多少", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.USER_DATA},
    {"bucket": "user_data", "q": "我的播放历史", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.USER_DATA},
    {"bucket": "user_data", "q": "我今天的点赞数", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.USER_DATA},
]


def _route_keyword(router: Router, question: str, ctx: dict) -> str:
    cands = router.route_candidates(question, ctx)
    if not cands:
        return WorkflowType.CHAT
    # 有 video_id 时 hybrid 会对 VIDEO_QA 加上下文分；keyword 回归对齐该行为
    if ctx.get("video_id"):
        kd = dict(cands)
        if not any(ex in question for ex in router.video_exclude):
            kd[WorkflowType.VIDEO_QA] = max(kd.get(WorkflowType.VIDEO_QA, 0.0), 0.5)
        cands = sorted(kd.items(), key=lambda x: x[1], reverse=True)
    return cands[0][0]


def run_ternary(router: Optional[Router] = None, *, fused: bool = False) -> Dict[str, Any]:
    router = router or Router()
    by_bucket: Dict[str, List[Tuple[bool, str, str, str]]] = {}
    rows = []
    for tc in TERNARY_CASES:
        ctx = tc.get("ctx") or {}
        if fused:
            got = router.hybrid_route(tc["q"], ctx)
        else:
            got = _route_keyword(router, tc["q"], ctx)
        ok = got == tc["expected"]
        rows.append((ok, tc["bucket"], tc["q"], tc["expected"], got))
        by_bucket.setdefault(tc["bucket"], []).append((ok, tc["q"], tc["expected"], got))

    total = len(rows)
    passed = sum(1 for r in rows if r[0])
    bucket_stats = {
        b: {"passed": sum(1 for x in items if x[0]), "total": len(items)}
        for b, items in by_bucket.items()
    }
    failures = [
        {"bucket": b, "q": q, "expected": exp, "got": got}
        for ok, b, q, exp, got in rows
        if not ok
    ]
    return {
        "mode": "fused" if fused else "keyword",
        "passed": passed,
        "total": total,
        "accuracy": passed / total if total else 0.0,
        "buckets": bucket_stats,
        "failures": failures,
    }

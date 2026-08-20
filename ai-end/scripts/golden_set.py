"""
黄金集评测：路由准确率分方法统计（关键词 / 语义 / LLM / 融合）。

用法: python scripts/golden_set.py [--limit 20] [--method-filter keyword|semantic|llm]

设计目标（替代旧 eval_agent.py 的 14 条直给关键词用例）：
1. 80~150 条用例，覆盖四类意图 + 大量歧义句/混淆样本
2. 输出 keyword / semantic / llm / fused 四种判定路径各自的准确率与平均耗时
3. 现场被问"为什么双路/为什么三阶段"时，能直接甩一张表
"""

import argparse
import logging
import sys
import time
from collections import defaultdict
from typing import Dict, List

sys.path.insert(0, ".")

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

from app.agents.workflows.constants import WorkflowType  # noqa: E402

VIDEO_ID = "video_demo_001"
USER_ID = "u_golden"

GOLDEN_CASES: List[dict] = [
    # ── VIDEO_QA（视频问答）──
    {"q": "这个视频讲了什么", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA, "tier": "easy"},
    {"q": "视频的重点是什么", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA, "tier": "easy"},
    {"q": "帮我总结这个视频", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA, "tier": "easy"},
    {"q": "这个视频的作者是谁", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA, "tier": "easy"},
    {"q": "讲解一下这个视频的内容", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA, "tier": "easy"},
    {"q": "视频里说了什么", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA, "tier": "easy"},
    {"q": "这个视频在讲什么主题", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA, "tier": "easy"},
    {"q": "你帮我看看这个视频讲了啥", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA, "tier": "ambiguous"},
    {"q": "这个视频好看吗", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA, "tier": "ambiguous"},
    {"q": "这个视频值不值得看", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA, "tier": "ambiguous"},
    {"q": "这个视频里有没有提到AI", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA, "tier": "ambiguous"},
    {"q": "视频的时长是多少", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA, "tier": "easy"},
    {"q": "这个视频的简介是什么", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA, "tier": "easy"},
    {"q": "这视频是哪个up主发的", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA, "tier": "easy"},
    {"q": "给我讲讲这个视频", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA, "tier": "easy"},
    {"q": "这个视频讲得怎么样", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA, "tier": "ambiguous"},
    # ── RECOMMEND（推荐）──
    {"q": "推荐一些好看的视频", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.RECOMMEND, "tier": "easy"},
    {"q": "有什么推荐的", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.RECOMMEND, "tier": "easy"},
    {"q": "推荐几个视频看看", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.RECOMMEND, "tier": "easy"},
    {"q": "有什么好看的视频", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.RECOMMEND, "tier": "easy"},
    {"q": "给我推荐点内容", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.RECOMMEND, "tier": "easy"},
    {"q": "热门视频有哪些", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.RECOMMEND, "tier": "easy"},
    {"q": "推荐两个视频", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.RECOMMEND, "tier": "easy"},
    {"q": "帮我找找好看的", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.RECOMMEND, "tier": "easy"},
    {"q": "有啥好看的", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.RECOMMEND, "tier": "easy"},
    {"q": "我想看点别的视频", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.RECOMMEND, "tier": "ambiguous"},
    {"q": "这个视频有没有类似的", "ctx": {"video_id": VIDEO_ID, "user_id": USER_ID}, "expected": WorkflowType.RECOMMEND, "tier": "ambiguous"},
    {"q": "喜欢看这个视频的人还会看什么", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.RECOMMEND, "tier": "ambiguous"},
    {"q": "给我推荐个轻松点的", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.RECOMMEND, "tier": "ambiguous"},
    {"q": "有什么新出的视频", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.RECOMMEND, "tier": "easy"},
    {"q": "推荐一点科普类的", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.RECOMMEND, "tier": "ambiguous"},
    {"q": "我该看什么", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.RECOMMEND, "tier": "ambiguous"},
    # ── USER_DATA（个人数据）──
    {"q": "我今天的点赞数", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.USER_DATA, "tier": "easy"},
    {"q": "我的收藏记录", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.USER_DATA, "tier": "easy"},
    {"q": "我看过哪些视频", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.USER_DATA, "tier": "easy"},
    {"q": "我的播放历史", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.USER_DATA, "tier": "easy"},
    {"q": "我点赞了哪些视频", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.USER_DATA, "tier": "easy"},
    {"q": "我的数据统计", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.USER_DATA, "tier": "easy"},
    {"q": "我最近收藏了什么", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.USER_DATA, "tier": "easy"},
    {"q": "我最近看了什么", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.USER_DATA, "tier": "easy"},
    {"q": "我收藏了哪些视频", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.USER_DATA, "tier": "easy"},
    {"q": "我的播放记录", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.USER_DATA, "tier": "easy"},
    {"q": "我本周点赞了多少", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.USER_DATA, "tier": "easy"},
    {"q": "我的硬币有多少", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.USER_DATA, "tier": "easy"},
    {"q": "我关注的up主有哪些", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.USER_DATA, "tier": "easy"},
    # ── CHAT（对话/平台）──
    {"q": "你们平台有什么功能", "expected": WorkflowType.CHAT, "tier": "easy"},
    {"q": "怎么使用这个平台", "expected": WorkflowType.CHAT, "tier": "easy"},
    {"q": "帮助", "expected": WorkflowType.CHAT, "tier": "easy"},
    {"q": "什么是ViewHub", "expected": WorkflowType.CHAT, "tier": "easy"},
    {"q": "你们支持哪些功能", "expected": WorkflowType.CHAT, "tier": "easy"},
    {"q": "你好", "expected": WorkflowType.CHAT, "tier": "easy"},
    {"q": "在吗", "expected": WorkflowType.CHAT, "tier": "easy"},
    {"q": "怎么上传视频", "expected": WorkflowType.CHAT, "tier": "easy"},
    {"q": "怎么删除视频", "expected": WorkflowType.CHAT, "tier": "easy"},
    {"q": "今天天气怎么样", "expected": WorkflowType.CHAT, "tier": "offtopic"},
    {"q": "你是谁", "expected": WorkflowType.CHAT, "tier": "easy"},
    {"q": "你会写代码吗", "expected": WorkflowType.CHAT, "tier": "offtopic"},
    {"q": "推荐一个餐厅给我", "expected": WorkflowType.CHAT, "tier": "offtopic"},
    {"q": "你知道b站吗", "expected": WorkflowType.CHAT, "tier": "offtopic"},
    {"q": "帮我写首诗", "expected": WorkflowType.CHAT, "tier": "offtopic"},
    {"q": "你吃饭了吗", "expected": WorkflowType.CHAT, "tier": "offtopic"},
    # ── 歧义 / 混淆（最容易翻车，重点盯）──
    {"q": "推荐我的收藏", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.USER_DATA, "tier": "ambiguous"},
    {"q": "我看过的视频里推荐几个", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.RECOMMEND, "tier": "ambiguous"},
    {"q": "这个视频和那个视频比哪个好", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA, "tier": "ambiguous"},
    {"q": "帮我分析一下这个视频的数据", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA, "tier": "ambiguous"},
    {"q": "我看视频的记录", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.USER_DATA, "tier": "ambiguous"},
    {"q": "点赞多的是哪些视频", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA, "tier": "ambiguous"},
    {"q": "这个视频好不好看", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA, "tier": "ambiguous"},
    {"q": "我的账号", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.CHAT, "tier": "ambiguous"},
    {"q": "推荐一个科技区的", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.RECOMMEND, "tier": "ambiguous"},
    {"q": "我点过哪些视频", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.USER_DATA, "tier": "ambiguous"},
    {"q": "这个视频里的up主", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA, "tier": "ambiguous"},
    {"q": "有什么功能可以用", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.CHAT, "tier": "ambiguous"},
    {"q": "帮我看看我的数据", "ctx": {"user_id": USER_ID}, "expected": WorkflowType.USER_DATA, "tier": "ambiguous"},
    {"q": "说说这个视频", "ctx": {"video_id": VIDEO_ID}, "expected": WorkflowType.VIDEO_QA, "tier": "ambiguous"},
]


def _stub_router_llm(router) -> None:
    """离线模式：禁用 LLM 裁决（分歧时走语义/关键词兜底），避免真实 API 调用。

    用于无 key/限流环境下跑通分方法统计；真实演示时去掉 --no-llm 走完整 LLM 裁决。
    """
    def _fallback(question, context=None):
        return None  # 与 _route_with_llm 返回 None 语义一致 → 走 fallback 分支
    router._route_with_llm = _fallback  # type: ignore[assignment]


def _method_stats(router, cases) -> Dict[str, dict]:
    """对每条用例同时跑 keyword 判定与融合判定，统计各路径准确率/耗时。"""

    stats: Dict[str, List] = defaultdict(list)  # method -> [(correct, latency)]
    fused_rows = []
    for tc in cases:
        q = tc["q"]
        ctx = tc.get("ctx") or {}
        expected = tc["expected"]

        # 关键词判定：route_candidates 的 top1（不调 embedding/LLM）
        t0 = time.time()
        kw_cands = router.route_candidates(q, ctx)
        kw_top = kw_cands[0][0] if kw_cands else WorkflowType.CHAT
        kw_lat = time.time() - t0
        stats["keyword"].append((kw_top == expected, kw_lat))

        # 融合判定（真实主路径）
        t1 = time.time()
        decision = router.hybrid_route_full(q, ctx)
        fused_lat = time.time() - t1
        stats["fused"].append((decision.workflow_type == expected, fused_lat))
        stats[decision.method].append((decision.workflow_type == expected, fused_lat))

        fused_rows.append((tc, kw_top, decision))
    return stats, fused_rows


def _print_table(stats: Dict[str, List]) -> None:
    print(f"\n{'='*58}")
    print("  路由准确率 · 分方法")
    print(f"{'='*58}")
    header = f"{'方法':<16}{'用例':>6}{'正确':>6}{'准确率':>9}{'平均耗时':>12}"
    print(header)
    print("-" * 58)
    order = ["keyword", "consensus", "semantic", "llm", "fallback", "fused"]
    for m in order:
        rows = stats.get(m)
        if not rows:
            continue
        n = len(rows)
        correct = sum(1 for c, _ in rows if c)
        acc = correct / n * 100
        avg = sum(lat for _, lat in rows) / n * 1000
        label = {
            "keyword": "关键词(单路)",
            "consensus": "融合·共识",
            "semantic": "融合·语义",
            "llm": "融合·LLM裁决",
            "fallback": "融合·兜底",
            "fused": "融合(整体)",
        }[m]
        print(f"{label:<18}{n:>6}{correct:>6}{acc:>8.1f}%{avg:>10.1f}ms")
    print("=" * 58)


def _print_errors(fused_rows) -> None:
    errors = [(tc, kw, dec) for tc, kw, dec in fused_rows if dec.workflow_type != tc["expected"]]
    if not errors:
        print("\n融合路由：全部命中 ✅")
        return
    print(f"\n融合路由误判 {len(errors)} 条：")
    for tc, kw, dec in errors:
        mark = "✅" if kw == tc["expected"] else "❌"
        print(f"  {mark} [{tc['expected']:<20s}] 预期→[{dec.workflow_type:<20s}] 实际  [{dec.method}]  {tc['q']}")


def main(limit: int = None, method_filter: str = None, no_llm: bool = False) -> int:
    global GOLDEN_CASES
    cases = GOLDEN_CASES if limit is None else GOLDEN_CASES[:limit]

    from app.agents.router import Router
    router = Router()

    if no_llm:
        _stub_router_llm(router)

    total = len(cases)
    correct = 0
    for tc in cases:
        decision = router.hybrid_route_full(tc["q"], tc.get("ctx") or {})
        if decision.workflow_type == tc["expected"]:
            correct += 1
    acc = correct / total * 100

    print(f"\n总用例: {total}  正确: {correct}  融合准确率: {acc:.1f}%")
    print("（按 tier 统计）")
    by_tier = defaultdict(lambda: [0, 0])
    for tc in cases:
        decision = router.hybrid_route_full(tc["q"], tc.get("ctx") or {})
        ok = decision.workflow_type == tc["expected"]
        by_tier[tc["tier"]][1] += 1
        if ok:
            by_tier[tc["tier"]][0] += 1
    for tier, (c, n) in sorted(by_tier.items()):
        print(f"  {tier:<12}{c}/{n}  ({c/max(n,1)*100:.0f}%)")

    stats, fused_rows = _method_stats(router, cases)
    if method_filter:
        only = defaultdict(list)
        for m, rows in stats.items():
            if m == method_filter:
                only[m] = rows
        stats = only
    _print_table(stats)
    _print_errors(fused_rows)

    return 0 if acc >= 80 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--method-filter", type=str, default=None)
    parser.add_argument("--no-llm", action="store_true", help="离线模式：禁用 LLM 裁决")
    args = parser.parse_args()
    sys.exit(main(limit=args.limit, method_filter=args.method_filter, no_llm=args.no_llm))

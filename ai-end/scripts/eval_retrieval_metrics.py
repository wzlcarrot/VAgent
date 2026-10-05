#!/usr/bin/env python3
"""
检索召回质量评测（recall@k / MRR / hit@k）。

背景：项目一直只评「路由 / 工具选择 / 步数」，**没有评「检索准不准」**。
本脚本补这一块：标注 query→相关片段，衡量排序质量。

双后端：
- `offline`（默认，零依赖）：对 fixture 内嵌语料做词面相似度排序（trigram Jaccard，
  与 memory 校准同公式）。给出**下限基线**，不依赖 DB。
- `dual`：调生产检索器 `dual_recall_and_rerank`（pgvector + 关键词 + rerank）。
  需要 DB 可用，且 fixture 语料应来自真实 DB（见下）。

指标：
- recall@k = top-k 命中的相关片段数 / 相关片段总数
- MRR       = 1 / 第一个相关片段的排名（未命中记 0）
- hit@k     = top-k 是否命中任一相关片段

口径提醒：
- 本环境 embedding 降级，`offline` 是词面基线，会**低估**语义召回；
- `dual` 模式要与 fixture 语料一致才有意义（用 DB 真实语料重建 fixture），
  否则映射不到 key，结果不可比。

用法:
    cd ai-end
    python3 scripts/eval_retrieval_metrics.py            # 离线词面基线
    python3 scripts/eval_retrieval_metrics.py --dual     # 生产检索器（需 DB）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "retrieval_eval_cases.jsonl"
TOP_KS = (1, 3, 5)

_WORD_RE = re.compile(r"[0-9a-zA-Z\u4e00-\u9fff]+")


def load_fixture() -> Tuple[List[dict], List[dict]]:
    corpus: List[dict] = []
    cases: List[dict] = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if "_corpus" in row:
            corpus = row["_corpus"]
        else:
            cases.append(row)
    return corpus, cases


def _trigrams(text: str) -> set:
    text = (text or "").strip().lower()
    grams = set()
    for word in _WORD_RE.findall(text):
        padded = "  " + word + " "
        for i in range(len(padded) - 2):
            grams.add(padded[i:i + 3])
    return grams


def lexical_similarity(a: str, b: str) -> float:
    ga, gb = _trigrams(a), _trigrams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def offline_rank(query: str, video_id: str, corpus: List[dict], k: int) -> List[str]:
    items = [c for c in corpus if c.get("video_id") == video_id]
    items.sort(key=lambda c: lexical_similarity(query, c.get("content", "")), reverse=True)
    return [c["key"] for c in items[:k]]


def _result_to_key(result: Dict[str, Any], corpus: List[dict]) -> str:
    bt = result.get("block_type") or result.get("key")
    if bt and any(c["key"] == bt for c in corpus):
        return bt
    content = str(result.get("content") or result.get("block_content") or "").strip()
    if content:
        for c in corpus:
            body = c.get("content", "")
            if body and (content[:20] in body or body[:20] in content):
                return c["key"]
    return ""


def dual_rank(query: str, video_id: str, corpus: List[dict], k: int) -> List[str]:
    from app.tools.ranker import dual_recall_and_rerank

    results = dual_recall_and_rerank(query, top_k=k, video_id=video_id)
    keys = []
    for r in results:
        key = _result_to_key(r, corpus)
        if key and key not in keys:
            keys.append(key)
    return keys


def _metrics(ranked: List[str], relevant: List[str]) -> Dict[str, float]:
    rel = set(relevant)
    out: Dict[str, float] = {}
    for k in TOP_KS:
        hit_k = len(set(ranked[:k]) & rel)
        out[f"recall@{k}"] = hit_k / len(rel) if rel else 0.0
    mrr = 0.0
    for i, key in enumerate(ranked, start=1):
        if key in rel:
            mrr = 1.0 / i
            break
    out["mrr"] = mrr
    out["hit@5"] = 1.0 if (set(ranked[:5]) & rel) else 0.0
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dual", action="store_true", help="用生产检索器（需 DB）")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--min-recall-at-5", type=float, default=0.0,
                        help="CI 门禁用：offline recall@5 下限（0=不卡）")
    args = parser.parse_args()

    corpus, cases = load_fixture()
    if args.limit:
        cases = cases[: args.limit]

    ranker: Callable[[str, str, List[dict], int], List[str]] = dual_rank if args.dual else offline_rank
    mode = "dual(生产检索器)" if args.dual else "offline(词面基线)"

    print(f"模式: {mode}   语料 {len(corpus)} 片段   用例 {len(cases)}")

    agg: Dict[str, float] = {f"recall@{k}": 0.0 for k in TOP_KS}
    agg.update({"mrr": 0.0, "hit@5": 0.0})
    rows = []
    for c in cases:
        ranked = ranker(c["query"], c["video_id"], corpus, max(TOP_KS))
        m = _metrics(ranked, c["relevant"])
        for kk in agg:
            agg[kk] += m[kk]
        rows.append((c, ranked, m))

    n = max(len(cases), 1)
    print("=" * 56)
    print("  检索召回质量")
    print("=" * 56)
    for kk in ("recall@1", "recall@3", "recall@5", "mrr", "hit@5"):
        print(f"  {kk:9} {agg[kk] / n * 100:6.1f}%")
    print("=" * 56)

    misses = [(c, ranked) for c, ranked, m in rows if m["recall@5"] == 0]
    if misses:
        print(f"  未召回用例 {len(misses)}（前 8）:")
        for c, ranked in misses[:8]:
            print(f"    {c['query']}  →  top: {ranked[:3]}  期望 {c['relevant']}")
    recall5 = agg["recall@5"] / n
    if args.min_recall_at_5 > 0 and recall5 + 1e-9 < args.min_recall_at_5:
        print(f"FAIL: recall@5 {recall5:.3f} < {args.min_recall_at_5}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

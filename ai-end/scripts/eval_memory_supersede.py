#!/usr/bin/env python3
"""
长期记忆「相似取代」阈值校准（借鉴 ragent 的阈值校准表）。

问题：`save_memory` 用 pg_trgm 的 `similarity() >= memory_supersede_threshold`（默认 0.6）
判断新旧记忆是否为同一偏好、该软失效旧的。**0.6 是拍的，没校准。**

句对分三类，回答不同问题：
- `dup`      同文/近乎同文的重复提取 —— 取代机制**应该**生效（去重）
- `para`     同一偏好的不同措辞     —— 语义上应取代，但**词面信号能否抓到**？
- `distinct` 不同偏好               —— 取代**绝不能**生效（误伤）

指标：dup 命中率、para 命中率、distinct 误伤率。

相似度口径：
- 优先连 DB 调 pg_trgm `similarity()`（与线上完全一致）
- DB 不可用时用 **Python 复刻 pg_trgm 公式**（trigram 集合 Jaccard：|A∩B|/|A∪B|，
  词按非字母数字切分、每词补成 "  word "）——离线也能出数，且与线上同算法。

用法:
    cd ai-end
    python3 scripts/eval_memory_supersede.py           # DB 可用则用 DB，否则用复刻
    python3 scripts/eval_memory_supersede.py --python  # 强制用 Python 复刻
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "memory_supersede_cases.jsonl"
THRESHOLDS = [0.3, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7, 0.8]

_WORD_RE = re.compile(r"[0-9a-zA-Z\u4e00-\u9fff]+")


def load_cases() -> List[dict]:
    rows = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def trigrams(text: str) -> set:
    """复刻 pg_trgm：词切分 + 每词补 '  word ' + 取 3-gram。"""
    text = (text or "").strip().lower()
    grams = set()
    for word in _WORD_RE.findall(text):
        padded = "  " + word + " "
        for i in range(len(padded) - 2):
            grams.add(padded[i:i + 3])
    return grams


def python_similarity(a: str, b: str) -> float:
    """pg_trgm 的 similarity = |trigram(A) ∩ trigram(B)| / |trigram(A) ∪ trigram(B)|。"""
    ga, gb = trigrams(a), trigrams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def make_db_similarity():
    """返回用 pg_trgm similarity() 的函数；DB 不可用/无扩展则返回 None。"""
    try:
        from app.tools.db import get_cursor

        with get_cursor() as cursor:
            if cursor is None:
                return None
            cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
            if cursor.fetchone() is None:
                return None

        def _sim(a: str, b: str) -> float:
            with get_cursor() as cursor:
                if cursor is None:
                    raise RuntimeError("db unavailable")
                cursor.execute("SELECT similarity(%s, %s) AS s", (a, b))
                row = cursor.fetchone()
                return float(row["s"]) if row else 0.0

        return _sim
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", action="store_true", help="强制用 Python 复刻 pg_trgm")
    args = parser.parse_args()

    cases = load_cases()
    counts = {k: sum(1 for c in cases if c["kind"] == k) for k in ("dup", "para", "distinct")}

    sim = None if args.python else make_db_similarity()
    source = "DB pg_trgm similarity()" if sim else "Python 复刻 pg_trgm（同算法）"
    if sim is None:
        sim = python_similarity

    sims = [(c, sim(c["a"], c["b"])) for c in cases]

    print(f"用例 {len(cases)}（dup {counts['dup']} / para {counts['para']} / distinct {counts['distinct']}）")
    print(f"相似度来源: {source}")
    print("=" * 72)
    print(f"{'阈值':>6} {'dup命中':>9} {'para命中':>9} {'distinct误伤':>12}")
    print("-" * 72)
    for th in THRESHOLDS:
        dup = sum(1 for c, s in sims if c["kind"] == "dup" and s >= th)
        para = sum(1 for c, s in sims if c["kind"] == "para" and s >= th)
        fp = sum(1 for c, s in sims if c["kind"] == "distinct" and s >= th)
        flag = "  ← 默认" if abs(th - 0.6) < 1e-9 else ""
        print(f"{th:>6.2f} {dup:>4}/{counts['dup']:<4} {para:>4}/{counts['para']:<4} {fp:>5}/{counts['distinct']:<6}{flag}")
    print("=" * 72)

    # 推荐：在「零误伤」前提下，最大化 dup 命中率
    best = None
    for th in THRESHOLDS:
        dup = sum(1 for c, s in sims if c["kind"] == "dup" and s >= th)
        fp = sum(1 for c, s in sims if c["kind"] == "distinct" and s >= th)
        if fp == 0 and (best is None or dup > best[1]):
            best = (th, dup)
    if best:
        print(f"零误伤下最优阈值: {best[0]:.2f}（dup 命中 {best[1]}/{counts['dup']}）")
    para_at_best = sum(1 for c, s in sims if c["kind"] == "para" and s >= (best[0] if best else 0.6))
    print(f"该阈值下 para（同义改写）命中: {para_at_best}/{counts['para']} —— 低说明词面信号抓不到语义改写")
    return 0


if __name__ == "__main__":
    sys.exit(main())

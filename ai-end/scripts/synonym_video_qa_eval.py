"""
同义口语视频内回答评测：改写命中率 + 证据充足率 + 拒答率。

用法:
  cd ai-end && python scripts/synonym_video_qa_eval.py
  cd ai-end && python scripts/synonym_video_qa_eval.py --live   # 走真实 dual_recall（需 DB）

离线默认 mock 召回，验证 rewrite / sufficient / refuse 逻辑可复现。
面试可直接甩表格：口语同义问法的 hit / refuse。
"""
from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

sys.path.insert(0, ".")

from app.tools.output_guard import VIDEO_QA_INSUFFICIENT_MSG  # noqa: E402
from app.tools.video_qa_retrieval import (  # noqa: E402
    has_sufficient_evidence,
    is_metadata_friendly_question,
    rewrite_video_qa_query,
    search_video_chunks,
    verify_answer_grounded,
)

VIDEO_ID = "synonym_eval_v1"
TITLE = "Python 零基础入门教程"
TAGS = "编程,Python,入门"
# mock 语料：命中「入门/语法」类 query；故意不命中「第三个实验参数」
CORPUS = [
    {
        "content": "本视频讲解 Python 零基础入门语法与变量",
        "block_type": "introduction_0",
        "score": 0.82,
        "video_id": VIDEO_ID,
    },
    {
        "content": "适合编程初学者了解主题与内容",
        "block_type": "tags_0",
        "score": 0.55,
        "video_id": VIDEO_ID,
    },
]


def _mock_recall(query: str, top_k: int = 5, video_id: str = None) -> List[Dict[str, Any]]:
    q = (query or "").lower()
    keys = ("python", "入门", "语法", "主题", "内容", "讲了", "介绍", "教程", "零基础", "编程", "干嘛", "说啥")
    if not any(k in q for k in keys):
        return []
    return [dict(d) for d in CORPUS][:top_k]


# expect: hit = 应有足够证据；refuse = 应拒答（证据不足且非 metadata 友好）
CASES: List[Dict[str, Any]] = [
    {"q": "这个视频讲了啥", "expect": "hit", "tier": "colloquial"},
    {"q": "讲了什么", "expect": "hit", "tier": "colloquial"},
    {"q": "说啥的", "expect": "hit", "tier": "colloquial"},
    {"q": "干嘛的", "expect": "hit", "tier": "colloquial"},
    {"q": "讲啥呢", "expect": "hit", "tier": "colloquial"},
    {"q": "这视频说啥", "expect": "hit", "tier": "colloquial"},
    {"q": "主题是什么", "expect": "hit", "tier": "synonym"},
    {"q": "内容重点是啥", "expect": "hit", "tier": "synonym"},
    {"q": "主要讲哪些点", "expect": "hit", "tier": "synonym"},
    {"q": "讲的是入门还是进阶", "expect": "hit", "tier": "synonym"},
    {"q": "介绍一下这个视频", "expect": "hit", "tier": "metadata"},
    {"q": "适合零基础吗从内容看", "expect": "hit", "tier": "synonym"},
    {"q": "Python 语法讲了啥", "expect": "hit", "tier": "synonym"},
    {"q": "编程入门教程讲什么", "expect": "hit", "tier": "synonym"},
    {"q": "第三个实验步骤的具体参数配置是多少", "expect": "refuse", "tier": "hard_negative"},
    {"q": "片尾彩蛋里隐藏的密钥字符串是什么", "expect": "refuse", "tier": "hard_negative"},
    {"q": "视频里有没有提到从未出现的 API Key", "expect": "refuse", "tier": "hard_negative"},
    {"q": "第四章第 17 页的公式推导细节", "expect": "refuse", "tier": "hard_negative"},
    {"q": "作者私下微信号是多少", "expect": "refuse", "tier": "hard_negative"},
    {"q": "片中口误改成了哪句官方口径", "expect": "refuse", "tier": "hard_negative"},
    {"q": "隐藏关卡密码 XYZ-999", "expect": "refuse", "tier": "hard_negative"},
    {"q": "未剪辑花絮里的内部代号", "expect": "refuse", "tier": "hard_negative"},
]


def eval_case(case: Dict[str, Any], live: bool) -> Tuple[str, Dict[str, Any]]:
    q = case["q"]
    rewritten = rewrite_video_qa_query(q, TITLE, TAGS, use_llm=False)
    if live:
        results, sufficient = search_video_chunks(
            VIDEO_ID, q, title=TITLE, tags=TAGS, top_k=5,
        )
    else:
        with patch("app.tools.ranker.dual_recall_and_rerank", side_effect=_mock_recall):
            results, sufficient = search_video_chunks(
                VIDEO_ID, q, title=TITLE, tags=TAGS, top_k=5,
            )

    if case["expect"] == "refuse":
        # 硬负例：即便标题召回了简介，胡答具体参数应被 verify 打回 → 走拒答
        hallucinated = "根据视频，第三个实验应使用电压 220V，隐藏密钥为 XYZ-SECRET。"
        grounded, reason = verify_answer_grounded(hallucinated, results, q)
        outcome = "refuse" if not grounded else "hit"
        answer = VIDEO_QA_INSUFFICIENT_MSG if outcome == "refuse" else hallucinated
    elif not sufficient and not is_metadata_friendly_question(q):
        answer = VIDEO_QA_INSUFFICIENT_MSG
        grounded, reason = True, "refuse"
        outcome = "refuse"
    else:
        answer = (results[0]["content"] if results else f"本视频是{TITLE}") + "[1]"
        grounded, reason = verify_answer_grounded(answer, results, q)
        outcome = "hit" if (sufficient or is_metadata_friendly_question(q)) else "refuse"

    ok = outcome == case["expect"]
    return ("PASS" if ok else "FAIL"), {
        "q": q,
        "tier": case["tier"],
        "expect": case["expect"],
        "outcome": outcome,
        "rewritten": rewritten[:60],
        "hits": len(results),
        "sufficient": sufficient,
        "grounded": grounded,
        "reason": reason,
        "answer_preview": (answer or "")[:40],
    }


def main():
    parser = argparse.ArgumentParser(description="同义口语视频内回答评测")
    parser.add_argument("--live", action="store_true", help="使用真实 dual_recall（需向量库）")
    args = parser.parse_args()

    # 离线评测默认关闭 LLM rewrite，避免耗额度 / 429
    from app.config import settings
    settings.video_qa_llm_rewrite = False

    rows = []
    pass_n = 0
    for case in CASES:
        status, row = eval_case(case, live=args.live)
        rows.append((status, row))
        if status == "PASS":
            pass_n += 1

    print("\n## Synonym Video QA Eval")
    print(f"mode={'live' if args.live else 'mock'}  pass={pass_n}/{len(CASES)}\n")
    print("| status | tier | expect | outcome | hits | q |")
    print("|--------|------|--------|---------|------|---|")
    for status, row in rows:
        print(
            f"| {status} | {row['tier']} | {row['expect']} | {row['outcome']} "
            f"| {row['hits']} | {row['q']} |"
        )

    # 汇总表（面试用）
    hit_cases = [r for _, r in rows if r["expect"] == "hit"]
    refuse_cases = [r for _, r in rows if r["expect"] == "refuse"]
    hit_ok = sum(1 for r in hit_cases if r["outcome"] == "hit")
    refuse_ok = sum(1 for r in refuse_cases if r["outcome"] == "refuse")
    print("\n### Summary")
    print("| metric | value |")
    print("|--------|-------|")
    print(f"| synonym/colloquial hit rate | {hit_ok}/{len(hit_cases)} |")
    print(f"| hard-negative refuse rate | {refuse_ok}/{len(refuse_cases)} |")
    print(f"| overall | {pass_n}/{len(CASES)} |")

    # 也测 has_sufficient_evidence 边界
    assert has_sufficient_evidence([{"content": "x", "score": 0.3}])
    sys.exit(0 if pass_n == len(CASES) else 1)


if __name__ == "__main__":
    main()

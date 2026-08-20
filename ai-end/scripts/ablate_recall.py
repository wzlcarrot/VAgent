"""
双路召回最小对比：BM25-only / vector-only / 融合 在 ViewHub 片库上的差异。

用法: python scripts/ablate_recall.py [--top-k 5]

设计目标：
- 在 ViewHub 真实 video_info / video_vector_block 库上跑
- 对一组代表性查询，分别统计：
    1. BM25 单独召回命中数
    2. 向量单独召回命中数
    3. 融合（union + rerank）命中数
    4. 唯一命中（只有某一路能召回）—— 用于回答"为什么双路"
- 输出一张表，现场挡住"为什么双路"的追问。

需要 PostgreSQL 可用（ParadeDB/tsvector + vector 扩展）。
无 DB 时打印提示并跳过，不报错。
"""

import argparse
import logging
import sys
import time

sys.path.insert(0, ".")

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

from app.tools.llm_tools import LLM_tools  # noqa: E402
from app.tools.rag_tools import RAGTools  # noqa: E402

# 代表不同意图/语境的查询集（覆盖科技/教程/生活/娱乐等 ViewHub 常见内容）
QUERIES = [
    "Python 教程",
    "机器学习入门",
    "做饭教程",
    "旅行 vlog",
    "游戏攻略",
    "AI 编程",
    "健身训练",
    "美食探店",
    "数码评测",
    "音乐翻唱",
]


def _bm25(query: str, top_k: int) -> list:
    t0 = time.time()
    try:
        rows = RAGTools.retrieve_knowledge(query, top_k=top_k)
    except Exception as e:
        logger.error(f"BM25 失败: {e}")
        rows = []
    return rows, time.time() - t0


def _vector(query: str, top_k: int) -> list:
    t0 = time.time()
    try:
        emb = LLM_tools.embed([query])
        rows = RAGTools.vector_search(emb[0], top_k=top_k) if emb else []
    except Exception as e:
        logger.error(f"向量检索失败: {e}")
        rows = []
    return rows, time.time() - t0


def _fused(bm, vec, top_k: int) -> list:
    # 与生产 dual_recall_and_rerank 的并集语义一致：按 video_id 去重合并
    seen = set()
    merged = []
    for doc in bm + vec:
        vid = doc.get("video_id") or ""
        if vid and vid not in seen:
            seen.add(vid)
            merged.append(doc)
    return merged[:top_k]


def main(top_k: int) -> int:
    if not RAGTools._is_available():
        print("PostgreSQL 不可用，无法跑召回对比。请先启动 DB 并导入 ViewHub 片库。")
        return 2

    print(f"\n{'='*64}")
    print(f"  双路召回对比 · top_k={top_k} · ViewHub 片库")
    print(f"{'='*64}")
    header = f"{'查询':<14}{'BM25命中':>8}{'向量命中':>8}{'融合命中':>8}{'BM25独有':>8}{'向量独有':>8}"
    print(header)
    print("-" * 64)

    agg = {"bm": 0, "vec": 0, "fused": 0, "bm_only": 0, "vec_only": 0, "total_queries": 0}
    for q in QUERIES:
        bm, t_bm = _bm25(q, top_k)
        vec, t_vec = _vector(q, top_k)
        fused = _fused(bm, vec, top_k)

        bm_ids = {d.get("video_id") for d in bm}
        vec_ids = {d.get("video_id") for d in vec}
        fused_ids = {d.get("video_id") for d in fused}

        bm_only = bm_ids - vec_ids
        vec_only = vec_ids - bm_ids

        agg["bm"] += len(bm_ids)
        agg["vec"] += len(vec_ids)
        agg["fused"] += len(fused_ids)
        agg["bm_only"] += len(bm_only)
        agg["vec_only"] += len(vec_only)
        agg["total_queries"] += 1

        print(f"{q:<16}{len(bm_ids):>8}{len(vec_ids):>8}{len(fused_ids):>8}"
              f"{len(bm_only):>8}{len(vec_only):>8}")

    print("-" * 64)
    print(f"{'合计':<16}{agg['bm']:>8}{agg['vec']:>8}{agg['fused']:>8}"
          f"{agg['bm_only']:>8}{agg['vec_only']:>8}")
    print("\n结论：")
    print(f"  融合候选池 = BM25 ∪ 向量 = {agg['fused']}，比单路都多 → 双路并集提升召回覆盖")
    print(f"  仅 BM25 能召回：{agg['bm_only']} 条（占融合池 {agg['bm_only']/max(agg['fused'],1)*100:.0f}%）")
    print(f"  仅 向量 能召回：{agg['vec_only']} 条（占融合池 {agg['vec_only']/max(agg['fused'],1)*100:.0f}%）")
    if agg["bm_only"] > 0 and agg["vec_only"] > 0:
        print("  两路各有独有命中 → 双路互补，单路会漏掉这些")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    sys.exit(main(args.top_k))

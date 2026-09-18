"""RAG 检索效果评测：只跑召回链路，不调用答案生成 LLM（借鉴 Ragent EvalController）。"""
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import settings
from app.routers._shared import require_auth
from app.tools.ranker import max_rerank_score, resolve_retrieval_budgets
from app.tools.video_qa_retrieval import rewrite_video_qa_query, search_video_chunks

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/rag/eval")
async def rag_eval(
    question: str = Query(..., min_length=1, max_length=2000),
    video_id: str = Query("", max_length=128),
    title: str = Query("", max_length=500),
    tags: str = Query("", max_length=500),
    top_k: int = Query(0, ge=0, le=20),
    _user_id: str = Depends(require_auth),
):
    if not settings.rag_eval_enabled:
        raise HTTPException(status_code=404, detail="rag eval API disabled")

    from app.agents.workflows import run_sync_in_executor

    start = time.perf_counter()
    effective_top_k = top_k or settings.rag_default_top_k
    rewritten = rewrite_video_qa_query(question, title, tags)

    if video_id:
        chunks, sufficient = await run_sync_in_executor(
            search_video_chunks,
            video_id,
            question,
            title=title,
            tags=tags,
            top_k=effective_top_k,
            rewrite_query=rewritten,
        )
    else:
        from app.tools.ranker import dual_recall_and_rerank

        chunks = await run_sync_in_executor(
            dual_recall_and_rerank,
            rewritten,
            effective_top_k,
            None,
        )
        from app.tools.video_qa_retrieval import has_sufficient_evidence

        sufficient = has_sufficient_evidence(chunks)

    recall_budget, rerank_limit, final_k = resolve_retrieval_budgets(effective_top_k)
    gate_floor = settings.rag_evidence_gate_min_score
    gate_passed = True
    if gate_floor > 0 and chunks:
        gate_passed = (max_rerank_score(chunks) or 0) >= gate_floor
    elif gate_floor > 0 and not chunks:
        gate_passed = False

    latency_ms = int((time.perf_counter() - start) * 1000)
    return {
        "question": question,
        "rewritten_query": rewritten,
        "video_id": video_id or None,
        "budget": {
            "recall_budget": recall_budget,
            "rerank_candidate_limit": rerank_limit,
            "default_top_k": final_k,
        },
        "gate_passed": gate_passed,
        "evidence_sufficient": sufficient,
        "latency_ms": latency_ms,
        "chunks": [
            {
                "id": f"{c.get('video_id', '')}:{i}",
                "video_id": c.get("video_id") or "",
                "score": float(c.get("score") or 0),
                "block_type": c.get("block_type") or "chunk",
                "snippet": (c.get("content") or c.get("block_content") or "")[:200],
            }
            for i, c in enumerate(chunks)
            if isinstance(c, dict)
        ],
        "chunk_ids": [
            f"{c.get('video_id', '')}:{i}"
            for i, c in enumerate(chunks)
            if isinstance(c, dict)
        ],
    }

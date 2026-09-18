"""EvidenceGate、检索漏斗与 RAG eval API 测试。"""
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import validate_rag_config
from app.tools.ranker import (
    apply_evidence_gate,
    max_rerank_score,
    resolve_retrieval_budgets,
)


def test_max_rerank_score():
    assert max_rerank_score([{"score": 0.2}, {"score": 0.8}]) == 0.8
    assert max_rerank_score([{"score": "bad"}]) is None
    assert max_rerank_score([]) is None


def test_evidence_gate_drops_low_batch():
    chunks = [{"content": "a", "score": 0.2}, {"content": "b", "score": 0.15}]
    assert apply_evidence_gate(chunks, min_top_score=0.35) == []


def test_evidence_gate_keeps_high_batch():
    chunks = [{"content": "a", "score": 0.2}, {"content": "b", "score": 0.9}]
    assert len(apply_evidence_gate(chunks, min_top_score=0.35)) == 2


def test_evidence_gate_disabled_when_zero():
    chunks = [{"content": "a", "score": 0.1}]
    assert apply_evidence_gate(chunks, min_top_score=0) == chunks


def test_evidence_gate_passes_when_no_scores():
    chunks = [{"content": "a"}]
    # 兼容旧行为：显式关闭 fail-closed
    with patch("app.config.settings.rag_evidence_gate_fail_closed_missing_score", False):
        assert apply_evidence_gate(chunks, min_top_score=0.35) == chunks


def test_evidence_gate_fail_closed_when_no_scores():
    chunks = [{"content": "a"}, {"content": "b"}]
    with patch("app.config.settings.rag_evidence_gate_fail_closed_missing_score", True):
        assert apply_evidence_gate(chunks, min_top_score=0.35) == []


def test_resolve_retrieval_budgets_respects_top_k():
    with patch("app.config.settings.rag_recall_budget", 10), \
         patch("app.config.settings.rag_rerank_candidate_limit", 15), \
         patch("app.config.settings.rag_default_top_k", 5):
        recall, rerank_limit, final_k = resolve_retrieval_budgets(8)
    assert final_k == 8
    assert recall >= 8
    assert rerank_limit >= 8


def test_validate_rag_config_rejects_bad_budget():
    with patch("app.config.settings.rag_default_top_k", 10), \
         patch("app.config.settings.rag_recall_budget", 5), \
         patch("app.config.settings.rag_rerank_candidate_limit", 20):
        with pytest.raises(ValueError, match="rag_recall_budget"):
            validate_rag_config()


def test_dual_recall_applies_evidence_gate():
    from app.tools.ranker import dual_recall_and_rerank

    low = [{"content": "kw", "video_id": "1", "score": 0.1}]
    with patch("app.tools.rag_tools.RAGTools.retrieve_knowledge", return_value=low), \
         patch("app.tools.rag_tools.RAGTools.vector_search", return_value=[]), \
         patch("app.tools.llm_tools.LLM_tools.embed", return_value=[[0.1]]), \
         patch("app.tools.ranker.rerank", return_value=[{"content": "kw", "score": 0.1}]), \
         patch("app.config.settings.rag_evidence_gate_min_score", 0.35):
        out = dual_recall_and_rerank("q", top_k=3, video_id="v1")
    assert out == []


def test_rag_eval_endpoint_disabled():
    from app.routers._shared import require_auth
    from app.routers.rag_eval import router as rag_eval_router

    app = FastAPI()
    app.include_router(rag_eval_router, prefix="/ai")
    app.dependency_overrides[require_auth] = lambda: "u1"
    client = TestClient(app)

    with patch("app.config.settings.rag_eval_enabled", False):
        resp = client.get("/ai/rag/eval", params={"question": "讲了什么"})
    assert resp.status_code == 404


def test_rag_eval_endpoint_returns_chunks():
    from app.routers._shared import require_auth
    from app.routers.rag_eval import router as rag_eval_router

    app = FastAPI()
    app.include_router(rag_eval_router, prefix="/ai")
    app.dependency_overrides[require_auth] = lambda: "u1"
    client = TestClient(app)

    fake_chunks = [{"content": "Python 入门", "score": 0.9, "video_id": "v1", "block_type": "intro"}]

    async def _fake_executor(fn, *args, **kwargs):
        return fake_chunks, True

    with patch("app.config.settings.rag_eval_enabled", True), \
         patch("app.agents.workflows.run_sync_in_executor", side_effect=_fake_executor):
        resp = client.get(
            "/ai/rag/eval",
            params={"question": "讲了什么", "video_id": "v1", "title": "教程"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["rewritten_query"]
    assert body["gate_passed"] is True
    assert body["evidence_sufficient"] is True
    assert len(body["chunks"]) == 1
    assert body["chunks"][0]["snippet"].startswith("Python")

"""检索召回指标（recall@k / MRR / hit@k）单元测试。"""
from scripts.eval_retrieval_metrics import _metrics, lexical_similarity, offline_rank


def test_metrics_perfect_hit():
    m = _metrics(["a", "b", "c"], ["a"])
    assert m["recall@1"] == 1.0
    assert m["recall@3"] == 1.0
    assert m["mrr"] == 1.0
    assert m["hit@5"] == 1.0


def test_metrics_total_miss():
    m = _metrics(["x", "y", "z"], ["a"])
    assert m["recall@1"] == 0.0
    assert m["recall@5"] == 0.0
    assert m["mrr"] == 0.0
    assert m["hit@5"] == 0.0


def test_metrics_mrr_rank_two():
    m = _metrics(["x", "a", "y"], ["a"])
    assert abs(m["mrr"] - 0.5) < 1e-9
    assert m["recall@1"] == 0.0
    assert m["recall@3"] == 1.0


def test_metrics_recall_at_k_partial():
    m = _metrics(["a", "x", "y"], ["a", "z"])
    assert abs(m["recall@1"] - 0.5) < 1e-9
    assert abs(m["recall@3"] - 0.5) < 1e-9


def test_offline_rank_orders_by_similarity():
    corpus = [
        {"key": "k1", "video_id": "v", "content": "番茄炒蛋 火候控制 油温"},
        {"key": "k2", "video_id": "v", "content": "Python 变量 循环"},
    ]
    ranked = offline_rank("火候怎么掌握", "v", corpus, 2)
    assert ranked[0] == "k1"


def test_offline_rank_scopes_by_video():
    corpus = [
        {"key": "k1", "video_id": "v1", "content": "火候"},
        {"key": "k2", "video_id": "v2", "content": "火候"},
    ]
    assert offline_rank("火候", "v1", corpus, 3) == ["k1"]


def test_lexical_similarity_bounds():
    assert lexical_similarity("abc", "abc") == 1.0
    assert lexical_similarity("", "abc") == 0.0

"""精排降级链单测：cross-encoder → LLM → 召回原始分。"""
from unittest.mock import patch


def _cands():
    return [
        {"content": "a", "score": 0.2},
        {"content": "b", "score": 0.9},
    ]


def test_rerank_prefers_cross_encoder():
    from app.tools import ranker

    cands = _cands()
    with patch.object(ranker, "_cross_encoder_score", return_value=[(cands[0], 0.9), (cands[1], 0.1)]), \
         patch.object(ranker, "_batch_llm_score", side_effect=AssertionError("成功时不应调用 LLM")), \
         patch("app.config.settings.rag_rerank_backend", "cross_encoder"):
        out = ranker.rerank("q", cands, top_k=1)
    assert out[0]["content"] == "a"
    assert out[0]["score"] == 0.9


def test_rerank_falls_back_to_llm_when_cross_encoder_unavailable():
    from app.tools import ranker

    cands = _cands()
    with patch.object(ranker, "_cross_encoder_score", return_value=None), \
         patch.object(ranker, "_batch_llm_score", return_value=[(cands[0], 0.7), (cands[1], 0.2)]) as m_llm, \
         patch("app.config.settings.rag_rerank_backend", "cross_encoder"):
        out = ranker.rerank("q", cands, top_k=1)
    assert out[0]["content"] == "a"
    m_llm.assert_called_once()


def test_cross_encoder_load_timeout_does_not_block():
    from app.tools import ranker

    ranker._cross_encoder = None
    ranker._cross_encoder_unavailable = False

    def _hang_join(self, timeout=None):
        return False

    with patch("app.tools.ranker.threading.Thread.start", return_value=None), \
         patch("app.tools.ranker.threading.Thread.join", _hang_join):
        assert ranker._get_cross_encoder() is None
    assert ranker._cross_encoder_unavailable is True
    ranker._cross_encoder_unavailable = False


def test_rerank_score_backend_skips_models():
    from app.tools import ranker

    cands = _cands()
    with patch.object(ranker, "_cross_encoder_score", side_effect=AssertionError("score 后端不应调用 cross-encoder")), \
         patch.object(ranker, "_batch_llm_score", side_effect=AssertionError("score 后端不应调用 LLM")), \
         patch("app.config.settings.rag_rerank_backend", "score"):
        out = ranker.rerank("q", cands, top_k=1)
    assert out[0]["content"] == "b"  # 原始分更高的 b 胜出


def test_parse_rerank_payload_accepts_object_and_array():
    from app.tools.ranker import _parse_rerank_payload

    arr = [{"index": 0, "score": 4}]
    assert _parse_rerank_payload(arr) == arr
    assert _parse_rerank_payload({"items": arr}) == arr
    assert _parse_rerank_payload({"index": 1, "score": 2}) == [{"index": 1, "score": 2}]
    assert _parse_rerank_payload(None) is None


def test_llm_rerank_empty_falls_back_to_lexical():
    from app.tools import ranker

    cands = [
        {"content": "Python 入门变量循环", "score": 0.1},
        {"content": "周末影评纪录片", "score": 0.9},
    ]
    with patch("app.tools.ranker.LLM_tools.chat_sync_json", return_value=None):
        out = ranker._batch_llm_score("Python 循环", cands)
    assert out[0][0]["content"] == "Python 入门变量循环"

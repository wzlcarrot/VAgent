"""查询归一化：提升缓存命中率（去空白/标点/大小写 + 同义词）。"""
from unittest.mock import MagicMock, patch

from app.agents.router import RouteDecision, Router
from app.utils.text_norm import normalize_query, normalize_text


class TestNormalize:
    def test_surface(self):
        assert normalize_text(" 怎么上传视频？ ") == "怎么上传视频"
        assert normalize_text("Hello, World!") == "helloworld"

    def test_query_synonyms(self):
        assert normalize_query("如何上传视频") == normalize_query("怎么上传视频")
        assert normalize_query("咋办") == normalize_query("怎么办")

    def test_equivalents_same_key(self):
        a = normalize_query("怎么上传视频？")
        b = normalize_query("如何 上传视频")
        c = normalize_query("怎么上传视频")
        assert a == b == c

    def test_word_order_boundary(self):
        # 语序不同 → 归一化抓不到（需语义缓存）；此处文档化边界
        assert normalize_query("视频如何上传") != normalize_query("怎么上传视频")


class TestRouteCacheNormalized:
    def test_equivalent_queries_hit_once(self):
        r = Router()
        r.clear_route_cache()
        impl = MagicMock(return_value=RouteDecision("chat_workflow", 1.0, "test"))
        with patch.object(Router, "_hybrid_route_full_impl", impl):
            r.hybrid_route_full("怎么上传视频")
            r.hybrid_route_full("怎么上传视频？")
            r.hybrid_route_full("如何上传视频")
        assert impl.call_count == 1  # 三种等价写法 → 只算一次

    def test_different_intent_new_key(self):
        r = Router()
        r.clear_route_cache()
        impl = MagicMock(return_value=RouteDecision("chat_workflow", 1.0, "test"))
        with patch.object(Router, "_hybrid_route_full_impl", impl):
            r.hybrid_route_full("怎么上传视频")
            r.hybrid_route_full("推荐点视频")
        assert impl.call_count == 2


class TestEmbeddingCacheNormalized:
    def test_punctuation_variant_hits_cache(self):
        r = Router()
        r._embedding_cache.clear()
        with patch("app.tools.llm_tools.LLM_tools.embed", return_value=[[0.1, 0.2]]) as m:
            r._get_embedding(["怎么上传视频"])
            r._get_embedding(["怎么上传视频？"])
        assert m.call_count == 1  # 去标点后同 key → 命中

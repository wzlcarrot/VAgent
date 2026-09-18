"""记忆语义召回（余弦）：关键词 ∪ 余弦双通道。"""
from unittest.mock import MagicMock, patch

from app.tools.memory_tools import MemoryTools, _cosine


def _ctx(cursor):
    ctx = MagicMock()
    ctx.__enter__.return_value = cursor
    ctx.__exit__.return_value = False
    return ctx


class TestCosine:
    def test_identical(self):
        assert abs(_cosine([1, 0], [1, 0]) - 1.0) < 1e-9

    def test_orthogonal(self):
        assert abs(_cosine([1, 0], [0, 1])) < 1e-9

    def test_empty(self):
        assert _cosine([], [1, 2]) == 0.0


class TestSemanticRecall:
    def test_semantic_rescues_keyword_miss(self):
        cand = [{"id": 7, "user_id": "u1", "type": "preference", "content": "用户喜欢科幻电影",
                 "source": "inferred", "score": 1.0, "tags": [], "effective_score": 1.0}]
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.side_effect = [[], cand]  # 关键词无命中 → 语义命中
        cursor.execute.side_effect = lambda sql, params=None: None

        with patch("app.tools.memory_tools.get_cursor", return_value=_ctx(cursor)), \
             patch("app.config.settings.memory_recall_fallback", False), \
             patch("app.config.settings.memory_semantic_recall_enabled", True), \
             patch("app.config.settings.memory_semantic_threshold", 0.45), \
             patch("app.config.settings.memory_semantic_weight", 0.5), \
             patch("app.tools.embed_tools.embedding_is_fallback", False), \
             patch("app.tools.embed_tools.embed",
                   return_value=[[1.0, 0.0, 0.0], [0.9, 0.1, 0.0]]):
            mems = MemoryTools.recall_memories("u1", query="有什么好看的片子", top_k=3)

        assert len(mems) == 1
        assert mems[0].id == 7

    def test_below_threshold_not_included(self):
        cand = [{"id": 7, "user_id": "u1", "type": "preference", "content": "用户喜欢做饭",
                 "source": "inferred", "score": 1.0, "tags": [], "effective_score": 1.0}]
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.side_effect = [[], cand]
        cursor.execute.side_effect = lambda sql, params=None: None

        with patch("app.tools.memory_tools.get_cursor", return_value=_ctx(cursor)), \
             patch("app.config.settings.memory_recall_fallback", False), \
             patch("app.config.settings.memory_semantic_recall_enabled", True), \
             patch("app.config.settings.memory_semantic_threshold", 0.45), \
             patch("app.config.settings.memory_semantic_weight", 0.5), \
             patch("app.tools.embed_tools.embedding_is_fallback", False), \
             patch("app.tools.embed_tools.embed",
                   return_value=[[1.0, 0.0, 0.0], [0.1, 0.9, 0.0]]):  # 余弦很低
            mems = MemoryTools.recall_memories("u1", query="有什么好看的片子", top_k=3)

        assert mems == []

    def test_embedding_fallback_skips_semantic(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = []
        cursor.execute.side_effect = lambda sql, params=None: None

        with patch("app.tools.memory_tools.get_cursor", return_value=_ctx(cursor)), \
             patch("app.config.settings.memory_recall_fallback", False), \
             patch("app.config.settings.memory_semantic_recall_enabled", True), \
             patch("app.tools.embed_tools.embedding_is_fallback", True), \
             patch("app.tools.embed_tools.embed") as mock_embed:
            MemoryTools.recall_memories("u1", query="科幻", top_k=3)

        mock_embed.assert_not_called()  # hash 兜底时不调 embedding

    def test_semantic_boosts_ranking(self):
        keyword_row = {"id": 1, "user_id": "u1", "type": "preference", "content": "用户喜欢科幻",
                       "source": "inferred", "score": 1.0, "tags": [], "effective_score": 1.0}
        sem_row = {"id": 2, "user_id": "u1", "type": "preference", "content": "用户喜欢太空题材",
                   "source": "inferred", "score": 1.0, "tags": [], "effective_score": 1.0}
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.side_effect = [[keyword_row], [sem_row]]
        cursor.execute.side_effect = lambda sql, params=None: None

        with patch("app.tools.memory_tools.get_cursor", return_value=_ctx(cursor)), \
             patch("app.config.settings.memory_semantic_recall_enabled", True), \
             patch("app.config.settings.memory_semantic_threshold", 0.45), \
             patch("app.config.settings.memory_semantic_weight", 0.5), \
             patch("app.tools.embed_tools.embedding_is_fallback", False), \
             patch("app.tools.embed_tools.embed",
                   return_value=[[1.0, 0.0], [0.95, 0.05]]):  # 语义高的排前面
            mems = MemoryTools.recall_memories("u1", query="太空", top_k=5)

        assert mems[0].id == 2  # 语义命中把 sem_row 提到最前


class TestRecallMode:
    def test_semantic_only_skips_keyword(self):
        cand = [{"id": 7, "user_id": "u1", "type": "preference", "content": "用户喜欢科幻电影",
                 "source": "inferred", "score": 1.0, "tags": [], "effective_score": 1.0}]
        cursor = MagicMock()
        captured = []
        cursor.fetchall.side_effect = [cand]
        cursor.execute.side_effect = lambda sql, params=None: captured.append(sql)

        with patch("app.tools.memory_tools.get_cursor", return_value=_ctx(cursor)), \
             patch("app.config.settings.memory_recall_mode", "semantic"), \
             patch("app.config.settings.memory_recall_fallback", False), \
             patch("app.config.settings.memory_semantic_recall_enabled", True), \
             patch("app.config.settings.memory_semantic_threshold", 0.45), \
             patch("app.config.settings.memory_semantic_weight", 0.5), \
             patch("app.tools.embed_tools.embedding_is_fallback", False), \
             patch("app.tools.embed_tools.embed", return_value=[[1.0, 0.0], [0.9, 0.1]]):
            mems = MemoryTools.recall_memories("u1", query="好看的片子", top_k=3)

        assert len(mems) == 1
        assert not any("ILIKE" in s or "similarity(" in s for s in captured)  # 跳过关键词通道

    def test_lexical_mode_skips_semantic(self):
        row = {"id": 1, "user_id": "u1", "type": "preference", "content": "用户喜欢科幻",
               "source": "inferred", "score": 1.0, "tags": [], "effective_score": 1.0}
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = [row]
        cursor.execute.side_effect = lambda sql, params=None: None

        with patch("app.tools.memory_tools.get_cursor", return_value=_ctx(cursor)), \
             patch("app.config.settings.memory_recall_mode", "lexical"), \
             patch("app.config.settings.memory_semantic_recall_enabled", True), \
             patch("app.tools.embed_tools.embed") as mock_embed:
            mems = MemoryTools.recall_memories("u1", query="科幻", top_k=3)

        mock_embed.assert_not_called()
        assert len(mems) == 1


class TestSemanticModeDegradation:
    def test_semantic_mode_degrades_to_keyword_when_embedding_down(self):
        """mode=semantic：embedding 不可用 → 降级 pg_trgm 关键词通道。"""
        row = {"id": 1, "user_id": "u1", "type": "preference", "content": "用户喜欢科幻",
               "source": "inferred", "score": 1.0, "tags": [], "effective_score": 1.0}
        cursor = MagicMock()
        captured = []
        cursor.fetchone.return_value = None  # 无 pg_trgm → ILIKE 分支
        cursor.fetchall.return_value = [row]
        cursor.execute.side_effect = lambda sql, params=None: captured.append(sql)

        with patch("app.tools.memory_tools.get_cursor", return_value=_ctx(cursor)), \
             patch("app.config.settings.memory_recall_mode", "semantic"), \
             patch("app.config.settings.memory_recall_fallback", True), \
             patch("app.config.settings.memory_semantic_recall_enabled", True), \
             patch("app.tools.embed_tools.embedding_is_fallback", True), \
             patch("app.tools.embed_tools.embed") as mock_embed:
            mems = MemoryTools.recall_memories("u1", query="科幻", top_k=3)

        mock_embed.assert_not_called()  # 兜底时不调 embedding
        assert len(mems) == 1
        assert any("ILIKE" in s for s in captured)  # 确实走了关键词通道


class TestAdditiveFusion:
    def test_low_base_high_cosine_can_rise(self):
        """加权融合：基础分低但语义高的记忆能冒头（乘法则不会）。"""
        keyword_row = {"id": 1, "user_id": "u1", "type": "preference", "content": "用户最近常看",
                       "source": "inferred", "score": 1.0, "tags": [], "effective_score": 1.0}
        sem_row = {"id": 2, "user_id": "u1", "type": "preference", "content": "用户喜欢科幻",
                   "source": "inferred", "score": 0.5, "tags": [], "effective_score": 0.5}
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.side_effect = [[keyword_row], [sem_row]]
        cursor.execute.side_effect = lambda sql, params=None: None

        with patch("app.tools.memory_tools.get_cursor", return_value=_ctx(cursor)), \
             patch("app.config.settings.memory_semantic_recall_enabled", True), \
             patch("app.config.settings.memory_semantic_threshold", 0.45), \
             patch("app.config.settings.memory_fusion_mode", "additive"), \
             patch("app.config.settings.memory_fusion_w_base", 0.6), \
             patch("app.config.settings.memory_fusion_w_sem", 0.4), \
             patch("app.tools.embed_tools.embedding_is_fallback", False), \
             patch("app.tools.embed_tools.embed", return_value=[[1.0, 0.0], [0.99, 0.01]]):
            mems = MemoryTools.recall_memories("u1", query="好看的片子", top_k=5)

        # id1 = 0.6×1.0 + 0.4×0 ≈ 0.60 ; id2 = 0.6×0.5 + 0.4×1.0 ≈ 0.70 → id2 冒头
        assert mems[0].id == 2

    def test_multiplicative_keeps_recency_dominant(self):
        """乘法：基础分低的不易翻盘（同数据下 id1 仍第一）。"""
        keyword_row = {"id": 1, "user_id": "u1", "type": "preference", "content": "用户最近常看",
                       "source": "inferred", "score": 1.0, "tags": [], "effective_score": 1.0}
        sem_row = {"id": 2, "user_id": "u1", "type": "preference", "content": "用户喜欢科幻",
                   "source": "inferred", "score": 0.5, "tags": [], "effective_score": 0.5}
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.side_effect = [[keyword_row], [sem_row]]
        cursor.execute.side_effect = lambda sql, params=None: None

        with patch("app.tools.memory_tools.get_cursor", return_value=_ctx(cursor)), \
             patch("app.config.settings.memory_semantic_recall_enabled", True), \
             patch("app.config.settings.memory_semantic_threshold", 0.45), \
             patch("app.config.settings.memory_fusion_mode", "multiplicative"), \
             patch("app.config.settings.memory_semantic_weight", 0.5), \
             patch("app.tools.embed_tools.embedding_is_fallback", False), \
             patch("app.tools.embed_tools.embed", return_value=[[1.0, 0.0], [0.99, 0.01]]):
            mems = MemoryTools.recall_memories("u1", query="好看的片子", top_k=5)

        # 乘法：id1 = 1.0 ; id2 = 0.5×1.5 = 0.75 → id1 仍第一
        assert mems[0].id == 1

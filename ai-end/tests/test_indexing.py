"""
视频索引链路测试：index_document / index_video / vector_search 的 block_type 兼容
"""
import pytest
from unittest.mock import patch, MagicMock
from app.tools.rag_tools import RAGTools


class TestIndexDocument:
    def test_index_document_empty_content(self):
        """空内容返回 False"""
        assert RAGTools.index_document("v1", "title", "") is False

    @patch("app.tools.chunker.chunk_document", return_value=["块一", "块二"])
    @patch("app.tools.llm_tools.LLM_tools.embed", return_value=[[0.1] * 384, [0.2] * 384])
    def test_index_document_embeds_per_chunk(self, mock_embed, mock_chunk):
        """每个 chunk 独立 embedding（不再共用整段向量）"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_pool.getconn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        with patch("app.tools.rag_tools.get_global_pool", return_value=mock_pool):
            RAGTools.index_document("v1", "title", "内容", block_weight=1)
            # 两个 chunk → 一次 embed 调用（列表），2 次 INSERT
            mock_embed.assert_called_once_with(["块一", "块二"])
            insert_calls = [c for c in mock_cursor.execute.call_args_list if "INSERT INTO video_vector_block" in c[0][0]]
            assert len(insert_calls) == 2

    @patch("app.tools.chunker.chunk_document", return_value=["块"])
    @patch("app.tools.llm_tools.LLM_tools.embed", return_value=[[0.1] * 384])
    def test_index_document_cleans_old_blocks(self, mock_embed, mock_chunk):
        """重复索引先清理该视频该类型的旧块（幂等）"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_pool.getconn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        with patch("app.tools.rag_tools.get_global_pool", return_value=mock_pool):
            RAGTools.index_document("v1", "title", "内容")
            delete_calls = [c for c in mock_cursor.execute.call_args_list if "DELETE FROM video_vector_block" in c[0][0]]
            assert len(delete_calls) == 1
            assert delete_calls[0][0][1] == ("v1", "title%")


class TestIndexVideo:
    @patch("app.tools.VideoTools.get_video_info")
    def test_index_video_missing(self, mock_get):
        mock_get.return_value = None
        result = RAGTools.index_video("nope")
        assert result["success"] is False
        assert "视频不存在" in result["error"]

    @patch("app.tools.rag_tools.RAGTools.index_document")
    @patch("app.tools.VideoTools.get_video_info")
    def test_index_video_three_parts(self, mock_get, mock_index):
        video = MagicMock()
        video.videoName = "机器学习入门"
        video.tags = "科技,教程"
        video.introduction = "这是一部机器学习的入门教程。"
        mock_get.return_value = video
        mock_index.return_value = True

        result = RAGTools.index_video("v1")
        assert result["success"] is True
        # title/tags/introduction 三个部分都索引
        assert set(result["parts"].keys()) == {"title", "tags", "introduction"}
        # block_weight：title=1, tags=2, introduction=3
        weights = [c[1]["block_weight"] for c in mock_index.call_args_list]
        assert weights == [1, 2, 3]

    @patch("app.tools.rag_tools.RAGTools.index_document")
    @patch("app.tools.VideoTools.get_video_info")
    def test_index_video_empty_fields_skipped(self, mock_get, mock_index):
        video = MagicMock()
        video.videoName = "视频A"
        video.tags = ""
        video.introduction = ""
        mock_get.return_value = video
        mock_index.return_value = True
        result = RAGTools.index_video("v1")
        assert result["parts"]["tags"]["indexed"] is False
        assert result["parts"]["introduction"]["indexed"] is False
        assert result["parts"]["title"]["indexed"] is True
        mock_index.assert_called_once()


class TestVectorSearchBlockType:
    @patch("app.tools.rag_tools.get_global_pool")
    def test_vector_search_sql_uses_like(self, mock_pool):
        """vector_search 用 LIKE 'title%' 匹配带序号的块"""
        mock_cursor = MagicMock()
        mock_pool.return_value.getconn.return_value.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []
        RAGTools.vector_search([0.1] * 384, top_k=3)
        sql = mock_cursor.execute.call_args[0][0]
        assert "block_type LIKE 'title%'" in sql
        assert "block_type LIKE 'tags%'" in sql
        assert "block_type LIKE 'introduction%'" in sql
        assert "block_type = 'title'" not in sql

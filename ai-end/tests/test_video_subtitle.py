"""字幕 PostgreSQL 存储与索引。"""
from unittest.mock import patch

from app.services.video_asr import merge_segments_for_index
from app.tools.rag_tools import RAGTools


def test_merge_segments_for_index():
    raw = [
        {"text": "你好", "start_s": 0.0, "end_s": 1.0},
        {"text": "世界", "start_s": 1.2, "end_s": 2.0},
        {"text": "下一句", "start_s": 10.0, "end_s": 11.0},
    ]
    merged = merge_segments_for_index(raw, max_gap_s=1.0, max_chars=200)
    assert len(merged) == 2
    assert merged[0]["text"] == "你好 世界"
    assert merged[0]["start_s"] == 0.0
    assert merged[1]["text"] == "下一句"


def test_index_subtitle_segments_mock_embed():
    segs = [
        {"text": "讲 Python 入门", "start_s": 12.0, "end_s": 18.0},
        {"text": "列表推导式示例", "start_s": 45.0, "end_s": 52.0},
    ]
    pool, conn, cursor = _pool_with_cursor()
    with patch("app.tools.llm_tools.LLM_tools.embed", return_value=[[0.1] * 384, [0.2] * 384]), \
         patch("app.tools.rag_tools.get_global_pool", return_value=pool):
        ok = RAGTools.index_subtitle_segments("v-sub", segs)
    assert ok is True
    assert cursor.execute.call_count >= 2


def test_index_video_subtitles_from_storage_only():
    with patch("app.config.settings.video_asr_enabled", False), \
         patch(
             "app.services.video_media_paths.list_video_files",
             return_value=[{"file_id": None, "file_index": 1, "file_path": ""}],
         ), \
         patch("app.services.video_subtitle_storage.load_subtitle_segments", return_value=[
             {"text": "已有字幕", "start_s": 3.0, "end_s": 6.0, "seq": 0, "source": "asr"},
         ]), \
         patch("app.services.video_subtitle_storage.subtitle_segment_count", return_value=1), \
         patch.object(RAGTools, "index_subtitle_segments", return_value=True) as mock_idx:
        out = RAGTools.index_video_subtitles("v1")
    assert out["indexed"] is True
    assert out["segment_count"] == 1
    mock_idx.assert_called_once()


def test_correct_segments_accepts_fix_and_keeps_timing():
    from app.services import video_subtitle_correction as corr

    segs = [{"text": "投胸", "start_s": 0.0, "end_s": 1.0}]
    with patch(
        "app.tools.llm_tools.LLM_tools.chat_sync_json",
        return_value={"lines": ["偷腥"]},
    ), patch("app.config.settings.video_asr_correct_enabled", True):
        out = corr.correct_segments(segs)
    assert out[0]["text"] == "偷腥"
    assert out[0]["start_s"] == 0.0 and out[0]["end_s"] == 1.0


def test_correct_segments_guards_against_length_blowup():
    from app.services import video_subtitle_correction as corr

    segs = [{"text": "谢谢", "start_s": 0.0, "end_s": 1.0}]
    with patch(
        "app.tools.llm_tools.LLM_tools.chat_sync_json",
        return_value={"lines": ["谢谢" * 50]},
    ), patch("app.config.settings.video_asr_correct_enabled", True):
        out = corr.correct_segments(segs)
    assert out[0]["text"] == "谢谢"


def test_correct_segments_passes_video_context():
    from app.services import video_subtitle_correction as corr

    captured = {}

    def fake(messages, **kwargs):
        captured["messages"] = messages
        return {"lines": ["你好"]}

    with patch("app.tools.llm_tools.LLM_tools.chat_sync_json", side_effect=fake), \
         patch("app.config.settings.video_asr_correct_enabled", True):
        corr.correct_segments(
            [{"text": "你好", "start_s": 0.0, "end_s": 1.0}],
            context="标题：测试视频",
        )
    assert "测试视频" in captured["messages"][1]["content"]


def test_bm25_helpers():
    from app.tools.rag_tools import _bm25_query_text, _bm25_to_unit

    assert _bm25_query_text("领导 电梯？") == "领导 电梯"
    assert _bm25_query_text("foo:bar+baz") == "foo bar baz"
    assert _bm25_query_text("!!!") == ""
    assert 0.0 < _bm25_to_unit(3) < 1.0
    assert _bm25_to_unit(0) == 0.0
    assert _bm25_to_unit(None) == 0.0


def _pool_with_cursor():
    from unittest.mock import MagicMock

    cursor = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value = cursor
    pool = MagicMock()
    pool.getconn.return_value = conn
    return pool, conn, cursor

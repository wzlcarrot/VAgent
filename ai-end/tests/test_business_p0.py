"""P0 业务：未索引拒答 / 质量看板。"""
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from app.models import VideoInfo
from app.services import business_quality as bq
from app.services import video_indexing as vi
from app.tools.output_guard import VIDEO_QA_NOT_INDEXED_MSG


def test_is_video_indexed_true():
    cursor = MagicMock()
    cursor.fetchone.return_value = {"?column?": 1}

    @contextmanager
    def _cursor():
        yield cursor

    with patch.object(vi, "get_cursor", _cursor):
        assert vi.is_video_indexed("v1") is True


def test_is_video_indexed_false():
    cursor = MagicMock()
    cursor.fetchone.return_value = None

    @contextmanager
    def _cursor():
        yield cursor

    with patch.object(vi, "get_cursor", _cursor):
        assert vi.is_video_indexed("v1") is False


def test_is_video_indexed_no_db_fail_open():
    @contextmanager
    def _null():
        yield None

    with patch.object(vi, "get_cursor", _null):
        assert vi.is_video_indexed("v1") is True


@patch("app.services.video_indexing.is_video_indexed", return_value=False)
@patch("app.agents.workflows.video_qa_workflow.VideoTools.get_video_info")
def test_video_info_node_not_indexed(mock_video, _mock_idx):
    from app.agents.workflows.video_qa_workflow import VideoQAState, supervisor_node, video_info_node

    mock_video.return_value = VideoInfo(
        videoId="v99", videoName="未索引视频",
        nickName="作者", duration=10, tags="test",
    )
    state: VideoQAState = {
        "question": "讲了什么",
        "video_id": "v99",
        "user_id": "u1",
        "session_id": "s1",
        "video_info": {},
        "video_error": "",
        "knowledge": [],
        "knowledge_sufficient": False,
        "citations": [],
        "corrective_applied": False,
        "react_steps": 0,
        "react_applied": False,
        "summary": "",
        "llm_response": "",
        "answer": "",
        "workflow_type": "video_qa_workflow",
    }
    out = video_info_node(state)
    assert out["video_error"] == VIDEO_QA_NOT_INDEXED_MSG
    state.update(out)
    sup = supervisor_node(state)
    assert VIDEO_QA_NOT_INDEXED_MSG in sup["answer"]


def test_query_business_quality_no_db():
    with patch.object(bq, "index_stats", return_value={"videos_pending": 2, "videos_indexed": 8, "videos_total": 10}), \
         patch.object(bq, "list_weekly_cases", return_value={"positive": 3, "negative": 1, "week": "2026-W09"}), \
         patch.object(bq, "_llm_circuit_snapshot", return_value={"status": "closed"}), \
         patch.object(bq, "_stream_permit_snapshot", return_value={"global_active": 1, "max_global": 10}), \
         patch.object(bq, "get_cursor") as mock_gc:
        @contextmanager
        def _null():
            yield None

        mock_gc.side_effect = _null
        r = bq.query_business_quality()
    assert r["metrics"]["videos_pending"] == 2
    assert r["metrics"]["feedback_helpful_rate"] == 0.75
    assert r["metrics"]["llm_circuit_state"] == "closed"
    assert r["index_sla"]["indexed_ratio"] == 0.8

"""视频内回答检索：改写、证据阈值、Corrective、引用。"""
from unittest.mock import patch

from app.tools.output_guard import VIDEO_QA_INSUFFICIENT_MSG
from app.tools.video_qa_retrieval import (
    build_citations,
    corrective_retrieve_once,
    has_sufficient_evidence,
    is_metadata_friendly_question,
    rewrite_video_qa_query,
    search_video_chunks,
    verify_answer_grounded,
)


def test_rewrite_strips_video_id_noise():
    q = rewrite_video_qa_query("这个视频讲了什么 video_id:1dJZCYwEKg", title="外卖", tags="", use_llm=False)
    assert "1dJZCYwEKg" not in q
    assert "讲了什么" in q
    assert "外卖" in q


def test_extract_video_id_from_text():
    from app.utils.video_id import extract_video_id_from_text

    assert extract_video_id_from_text("这个视频讲了什么 video_id:1dJZCYwEKg") == "1dJZCYwEKg"
    assert extract_video_id_from_text("id号是1dJZCYwEKg的视频具体讲什么") == "1dJZCYwEKg"
    assert extract_video_id_from_text("这个视频讲了什么") is None


def test_rewrite_colloquial():
    q = rewrite_video_qa_query("这个讲了啥", title="Python入门", tags="编程", use_llm=False)
    assert "这个讲了啥" in q
    assert "讲了什么" in q
    assert "Python入门" in q


def test_rewrite_llm_fallback_on_failure():
    with patch("app.config.settings.video_qa_llm_rewrite", True):
        with patch("app.tools.llm_tools.LLM_tools.chat_sync", side_effect=RuntimeError("boom")):
            q = rewrite_video_qa_query("讲了啥", title="T", tags="tag", use_llm=True)
    assert "讲了啥" in q
    assert "T" in q


def test_rewrite_llm_success():
    with patch("app.tools.llm_tools.LLM_tools.chat_sync", return_value="Python 入门 语法"):
        q = rewrite_video_qa_query("讲了啥", title="教程", tags="py", use_llm=True)
    assert "Python" in q
    assert "教程" in q


def test_is_metadata_friendly():
    assert is_metadata_friendly_question("这个视频讲了什么")
    assert is_metadata_friendly_question("讲了什么")
    assert not is_metadata_friendly_question("")
    assert not is_metadata_friendly_question("这个视频第三分钟说了什么")
    assert not is_metadata_friendly_question("第三个实验步骤的具体参数是多少")


def test_has_sufficient_evidence():
    assert has_sufficient_evidence([{"content": "x", "score": 0.3}])
    assert not has_sufficient_evidence([{"content": "x", "score": 0.1}])
    assert not has_sufficient_evidence([])


def test_build_citations():
    docs = [
        {"content": "Python 基础", "score": 0.9, "block_type": "introduction_0", "video_id": "v1"},
        {"content": "", "score": 0.5},
    ]
    cites = build_citations(docs)
    assert len(cites) == 1
    assert cites[0]["id"] == 1
    assert cites[0]["snippet"] == "Python 基础"
    assert cites[0]["video_id"] == "v1"


def test_verify_answer_grounded():
    docs = [{"content": "Python 入门语法讲解", "score": 0.8}]
    ok, reason = verify_answer_grounded("这门课讲 Python 入门语法[1]", docs, "讲了什么")
    assert ok and reason == "has_citation_markers"
    ok2, _ = verify_answer_grounded("完全无关的天文学结论", docs, "第三个实验参数是多少")
    assert not ok2


def test_search_video_chunks_two_rounds():
    low = [{"content": "a", "score": 0.1, "video_id": "v1"}]
    high = [{"content": "b", "score": 0.8, "video_id": "v1"}]

    with patch("app.config.settings.video_qa_llm_rewrite", False):
        with patch("app.tools.ranker.dual_recall_and_rerank", side_effect=[low, high]) as mock:
            results, ok = search_video_chunks("v1", "具体参数是多少", title="T", tags="tag")
    assert mock.call_count == 2
    assert ok is True
    assert results[0]["content"] == "b"


def test_search_video_chunks_single_round_metadata():
    hits = [{"content": "intro", "score": 0.1, "video_id": "v1"}]
    with patch("app.config.settings.video_qa_llm_rewrite", False):
        with patch("app.tools.ranker.dual_recall_and_rerank", return_value=hits) as mock:
            results, ok = search_video_chunks("v1", "讲了什么", title="T")
    assert ok is True
    assert len(results) == 1
    assert mock.call_args.kwargs.get("video_id") == "v1" or (
        mock.call_args.args and len(mock.call_args.args) >= 1
    )
    # 所有调用必须带 video_id=
    for call in mock.call_args_list:
        assert call.kwargs.get("video_id") == "v1"


def test_filter_scoped_chunks_drops_cross_video():
    from app.tools.video_qa_retrieval import filter_scoped_chunks

    chunks = [
        {"content": "本片", "video_id": "v1", "score": 0.9},
        {"content": "别的片", "video_id": "v2", "score": 0.95},
        {"content": "无 id", "score": 0.5},
    ]
    kept = filter_scoped_chunks(chunks, "v1")
    assert len(kept) == 1
    assert kept[0]["content"] == "本片"
    assert kept[0]["video_id"] == "v1"


def test_search_video_chunks_falls_back_to_title_when_empty():
    with patch("app.config.settings.video_qa_llm_rewrite", False):
        with patch("app.tools.ranker.dual_recall_and_rerank", return_value=[]):
            results, ok = search_video_chunks("v1", "这个视频讲了什么", title="外卖小哥")
    assert ok is True
    assert results[0]["content"] == "外卖小哥"
    assert results[0]["block_type"] == "metadata"


def test_search_video_chunks_filters_cross_video_pollution():
    polluted = [
        {"content": "wrong", "score": 0.99, "video_id": "other"},
        {"content": "ok", "score": 0.5, "video_id": "v1"},
    ]
    with patch("app.config.settings.video_qa_llm_rewrite", False):
        with patch("app.tools.ranker.dual_recall_and_rerank", return_value=polluted):
            results, _ = search_video_chunks("v1", "讲了什么", title="T")
    assert len(results) == 1
    assert results[0]["video_id"] == "v1"
    assert results[0]["content"] == "ok"


def test_corrective_retrieve_once_merges():
    existing = [{"content": "old", "score": 0.2, "video_id": "v1"}]
    extra = [{"content": "new better", "score": 0.9, "video_id": "v1"}]
    with patch("app.tools.ranker.dual_recall_and_rerank", return_value=extra):
        merged, ok = corrective_retrieve_once(
            "v1", "讲了什么", title="T", tags="tag", existing=existing,
        )
    assert ok is True
    assert any(d["content"] == "new better" for d in merged)


def test_strip_evidence_footer():
    from app.tools.video_qa_retrieval import strip_evidence_footer

    text = "这是回答。\n\n依据：\n[1] 片段一\n[2] 片段二"
    assert strip_evidence_footer(text) == "这是回答。"


def test_format_evidence_prompt_and_footer():
    from app.tools.video_qa_retrieval import format_evidence_footer, format_evidence_for_prompt

    docs = [
        {"content": "Python 基础语法介绍", "block_type": "introduction_0", "score": 0.9},
        {"content": "适合零基础", "block_type": "tags_0", "score": 0.6},
    ]
    prompt = format_evidence_for_prompt(docs)
    assert "[1]" in prompt and "[2]" in prompt
    footer = format_evidence_footer(docs)
    assert "依据：" in footer
    assert "[1]" in footer


def test_llm_node_insufficient_evidence():
    from app.agents.workflows.video_qa_workflow import VideoQAState, llm_node

    state: VideoQAState = {
        "question": "第三个实验的具体参数配置是多少",
        "video_id": "123",
        "user_id": "",
        "session_id": "",
        "video_info": {"title": "Python教程", "introduction": "入门"},
        "video_error": "",
        "knowledge": [],
        "knowledge_sufficient": False,
        "citations": [],
        "corrective_applied": False,
        "summary": "",
        "llm_response": "",
        "answer": "",
        "workflow_type": "video_qa_workflow",
    }
    out = llm_node(state)
    assert out["answer"] == VIDEO_QA_INSUFFICIENT_MSG


def test_corrective_node_appends_footer_and_citations():
    from app.agents.workflows.video_qa_workflow import VideoQAState, corrective_node

    state: VideoQAState = {
        "question": "这个视频讲了什么",
        "video_id": "123",
        "user_id": "",
        "session_id": "",
        "video_info": {"title": "Python教程", "introduction": "入门", "author": "张三", "duration": 10, "tags": "py"},
        "video_error": "",
        "knowledge": [{"content": "Python入门知识点", "block_type": "introduction_0", "score": 0.9}],
        "knowledge_sufficient": True,
        "citations": [],
        "corrective_applied": False,
        "summary": "",
        "llm_response": "这是一门入门课[1]。",
        "answer": "这是一门入门课[1]。",
        "workflow_type": "video_qa_workflow",
    }
    with patch("app.config.settings.video_qa_corrective", True):
        out = corrective_node(state)
    assert "依据：" not in out["answer"]
    assert "入门课" in out["answer"]
    assert out["citations"] and out["citations"][0]["snippet"].startswith("Python")


def test_corrective_node_rerequires_when_ungrounded():
    from app.agents.workflows.video_qa_workflow import VideoQAState, corrective_node

    state: VideoQAState = {
        "question": "第三个实验的具体参数配置是多少",
        "video_id": "123",
        "user_id": "",
        "session_id": "s1",
        "video_info": {"title": "Python教程", "video_id": "123", "tags": "py"},
        "video_error": "",
        "knowledge": [{"content": "Python入门", "score": 0.3}],
        "knowledge_sufficient": True,
        "citations": [],
        "corrective_applied": False,
        "summary": "",
        "llm_response": "火星上有液态水组成的海洋系统。",
        "answer": "火星上有液态水组成的海洋系统。",
        "workflow_type": "video_qa_workflow",
    }
    with patch("app.config.settings.video_qa_corrective", True):
        with patch(
            "app.agents.workflows.video_qa_workflow.corrective_retrieve_once",
            return_value=([{"content": "无关简介", "score": 0.2}], False),
        ):
            with patch(
                "app.agents.workflows.video_qa_workflow.invoke_with_governor",
                side_effect=lambda *a, **k: a[3](),
            ):
                with patch(
                    "app.agents.workflows.video_qa_workflow.LLM_tools.chat_sync",
                    return_value="仍然胡编的实验电压是 999V。",
                ):
                    out = corrective_node(state)
    assert out["corrective_applied"] is True
    assert out["answer"] == VIDEO_QA_INSUFFICIENT_MSG

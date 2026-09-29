"""对话记忆（Memory）测试：视频问答指代消解。"""
from unittest.mock import patch

from app.agents.workflows import video_qa_workflow as vq


def test_generate_answer_injects_history():
    captured = {}

    def _fake_chat(messages, **kwargs):
        captured["messages"] = messages
        return "回答[1]"

    history = [
        {"user": "这个视频讲什么", "assistant": "讲 Python 入门[1]"},
        {"user": "它的作者是谁"},
    ]
    with patch("app.agents.workflows.video_qa_workflow.LLM_tools.chat_sync", side_effect=_fake_chat):
        out = vq._generate_answer(
            "它的作者是谁",
            {"title": "Python教程"},
            [{"content": "作者是李四", "score": 0.9}],
            "",
            history,
        )
    assert out == "回答[1]"
    prompt = captured["messages"][1]["content"]
    assert "对话历史" in prompt
    assert "这个视频讲什么" in prompt
    assert "讲 Python 入门" in prompt


def test_format_history_caps_rounds():
    history = [{"user": f"q{i}", "assistant": f"a{i}"} for i in range(10)]
    text = vq._format_history(history, max_rounds=2)
    assert "q9" in text and "q8" in text
    assert "q0" not in text


def test_format_history_ignores_non_dict():
    text = vq._format_history(["bad", None, {"user": "有效", "assistant": "答"}], max_rounds=5)
    assert "有效" in text


def test_run_video_qa_workflow_accepts_history():
    """workflow 接受 conversation_history 且图执行不报错。"""
    with patch("app.agents.workflows.video_qa_workflow.VideoTools.get_video_info", return_value=None), \
         patch("app.services.video_indexing.is_video_indexed", return_value=False):
        result = vq.run_video_qa_workflow(
            "它讲什么",
            video_id="v1",
            session_id="s1",
            conversation_history=[{"user": "上一个问题", "assistant": "上一个回答"}],
        )
    assert result["workflow_type"] == "video_qa_workflow"

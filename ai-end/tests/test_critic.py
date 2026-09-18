"""独立评审 Agent（Critic / Reflection）测试。"""
from unittest.mock import patch

from app.agents.critic import critique_answer

EVIDENCE = [{"content": "Python 是一门编程语言，适合入门。", "score": 0.9, "video_id": "v1"}]


def test_critic_passes_when_grounded():
    with patch("app.config.settings.video_qa_critic_enabled", True), \
         patch("app.harness.llm_replay.replay_enabled", return_value=False), \
         patch("app.tools.llm_tools.LLM_tools.chat_sync", return_value="OK"):
        result = critique_answer("讲了什么", "Python 是编程语言[1]。", EVIDENCE)
    assert result.ok is True
    assert result.source == "llm"


def test_critic_flags_ungrounded():
    with patch("app.config.settings.video_qa_critic_enabled", True), \
         patch("app.harness.llm_replay.replay_enabled", return_value=False), \
         patch(
             "app.tools.llm_tools.LLM_tools.chat_sync",
             return_value="PROBLEM: 编造了嘉宾信息",
         ):
        result = critique_answer("讲了什么", "视频里邀请了张三做嘉宾。", EVIDENCE)
    assert result.ok is False
    assert "编造" in result.issue
    assert result.source == "llm"


def test_critic_disabled_is_fail_open():
    with patch("app.config.settings.video_qa_critic_enabled", False):
        result = critique_answer("q", "a", EVIDENCE)
    assert result.ok is True
    assert result.source == "disabled"


def test_critic_unparseable_verdict_is_fail_open():
    with patch("app.config.settings.video_qa_critic_enabled", True), \
         patch("app.harness.llm_replay.replay_enabled", return_value=False), \
         patch("app.tools.llm_tools.LLM_tools.chat_sync", return_value="嗯……我不确定"):
        result = critique_answer("q", "回答[1]", EVIDENCE)
    assert result.ok is True


def test_critic_empty_answer_flags():
    with patch("app.config.settings.video_qa_critic_enabled", True):
        result = critique_answer("q", "", EVIDENCE)
    assert result.ok is False
    assert result.issue == "empty_answer"


def test_critic_replay_flags_missing_evidence():
    with patch("app.config.settings.video_qa_critic_enabled", True), \
         patch("app.harness.llm_replay.replay_enabled", return_value=True):
        result = critique_answer("讲了什么", "完全是编造的内容", [])
    assert result.ok is False
    assert result.source == "replay"


def test_critic_replay_passes_with_citation():
    with patch("app.config.settings.video_qa_critic_enabled", True), \
         patch("app.harness.llm_replay.replay_enabled", return_value=True):
        result = critique_answer("讲了什么", "Python 入门[1]。", EVIDENCE)
    assert result.ok is True
    assert result.source == "replay"

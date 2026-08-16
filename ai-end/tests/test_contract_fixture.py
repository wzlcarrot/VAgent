"""
前后端联调契约测试：锁死后端 SSE 事件格式。

前端 tests/contract.agreement.test.ts 用同一组固定样本驱动 parseSSELine。
本测试断言后端真实 stream 输出的事件结构必须匹配这些样本，
防止后端改字段名/事件类型导致前端解析器（未同步改）契约断裂。

事件契约（前端 parseSSELine 消费）：
- {"type":"status","stage":"routing","label":"分析意图"}
- {"type":"status","stage":"parallel","label":"多Agent并行分析"}
- {"type":"status","stage":"generating","label":"生成回答"}
- {"type":"text","content":"..."}
- {"type":"status","stage":"done","label":"完成"}
- data: [DONE]  （终止哨兵）
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client():
    """进程内 TestClient：触发 lifespan、可携带 cookie、无需真实网络。"""
    with TestClient(app) as c:
        yield c


class TestSSEContract:
    """验证真实 stream 输出符合前端 parseSSELine 可消费的契约。"""

    def _stream_lines(self, client):
        do_login(client)
        with client.stream("POST", "/ai/chat/stream", json={"question": "你好"}) as r:
            assert r.status_code == 200
            body = "".join(r.iter_text())
        return body.splitlines()

    @staticmethod
    def _parse_events(lines):
        """解析 SSE 行为结构化事件；DONE 哨兵 yield None，JSON 事件 yield dict。"""
        for line in lines:
            if not line.startswith("data: "):
                continue
            data = line[6:].strip()
            if data == "[DONE]":
                yield None
                continue
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and parsed.get("type"):
                yield parsed

    def test_emits_status_and_text_and_done_events(self, client):
        events = list(self._parse_events(self._stream_lines(client)))
        types = [e["type"] for e in events if e is not None]

        # 事件序列契约：status 阶段 + text 内容，[DONE] 必须最后出现（前端终止流）
        # 注意：done stage 仅在 LLM 成功路径出现（fallback 路径跳过），故不作强制断言
        assert "status" in types
        assert "text" in types
        assert events[-1] is None  # [DONE] 必须最后出现（前端 parseSSELine 遇 DONE 终止）

    def test_status_events_have_expected_shape(self, client):
        """前端 parseSSELine 依赖 stage/label 字段，缺字段会导致解析失败。"""
        status_stages = []
        for e in self._parse_events(self._stream_lines(client)):
            if e is None or e.get("type") != "status":
                continue
            # 契约：status 事件必须有 stage 和 label
            assert "stage" in e, f"status 事件缺少 stage: {e}"
            assert "label" in e, f"status 事件缺少 label: {e}"
            status_stages.append(e["stage"])

        assert status_stages, "至少一个 status 事件"
        # 前端 stepConfig 认识这些 stage：routing/retrieval/generating/done
        known = {"routing", "retrieval", "generating", "done", "clarifying", "parallel"}
        for s in status_stages:
            assert s in known, f"未知 stage: {s}（前端 WorkflowIndicator 无法映射）"

    def test_text_events_have_string_content(self, client):
        """前端 parseSSELine 的 text 事件用 content 渲染，必须是字符串。"""
        text_contents = []
        for e in self._parse_events(self._stream_lines(client)):
            if e is None or e.get("type") != "text":
                continue
            assert isinstance(e.get("content"), str), f"text.content 非字符串: {e}"
            text_contents.append(e["content"])

        assert text_contents, "至少一个 text 事件"


def do_login(client, email="test@viewhub.com", password="123456"):
    resp = client.post("/ai/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp

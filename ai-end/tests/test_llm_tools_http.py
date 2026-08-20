"""
LLM HTTP 适配层测试：用 httpx mock 覆盖核心调用路径，无真实网络。

覆盖：
- chat / chat_sync / chat_sync_with_usage / chat_with_tools / chat_sync_json / chat_sync_typed
- stream_chat（含 <think> 跨 chunk 过滤、4xx 不重试、重试策略）
- retry 逻辑（429/5xx/超时/连接错误、非重试 4xx）
- abortable client（超时取消范围）
- embedding（_get_embed_model 三路降级、hash fallback、embed 失败）
"""
import asyncio
from unittest.mock import MagicMock, patch

import httpx
import pytest
from pydantic import BaseModel

from app.tools.llm_tools import (
    LLM_tools,
    _abortable_http_client,
    _build_payload,
    _call_with_retry_sync,
    _get_headers,
    _HashEmbedder,
    _is_retryable_http_status,
    _resolve_provider,
    _safe_get_content,
    _safe_get_tool_call,
    _safe_get_usage,
    _strip_think_blocks,
    aclose_async_client,
    close_http_clients,
)


def _ok_response(content="你好", tool_calls=None, usage=None):
    msg = {"message": {"content": content}}
    if tool_calls is not None:
        msg["message"]["tool_calls"] = tool_calls
    data = {"choices": [msg]}
    if usage:
        data["usage"] = usage
    resp = MagicMock()
    resp.json.return_value = data
    resp.status_code = 200
    return resp


async def _async_gen(items):
    for item in items:
        yield item


def _stream_ctx(lines, status_code=200, body=b""):
    """返回一个可作 client.stream 上下文的 mock：aiter_lines 是真正的 async 迭代。"""
    client = MagicMock()
    cm = client.stream.return_value
    cm.__aenter__.return_value.status_code = status_code
    cm.__aenter__.return_value.aiter_lines = lambda: _async_gen(lines)

    async def _aread():
        return body
    cm.__aenter__.return_value.aread = _aread
    return client


def _sync_client_ok(*args, **kwargs):
    client = MagicMock()
    client.post.return_value = _ok_response()
    return client


# ─── 纯函数 / 工具函数 ───
def test_is_retryable_http_status():
    for code in (408, 425, 429, 500, 502, 503, 504):
        assert _is_retryable_http_status(code)
    assert not _is_retryable_http_status(400)
    assert not _is_retryable_http_status(401)
    assert not _is_retryable_http_status(200)


def test_get_headers():
    h = _get_headers("key123")
    assert h["Authorization"] == "Bearer key123"
    assert h["Content-Type"] == "application/json"


def test_build_payload_basic_and_stream():
    p = _build_payload([{"role": "user", "content": "hi"}], "m", 0.7, 100)
    assert p["model"] == "m" and p["temperature"] == 0.7 and p["max_tokens"] == 100
    ps = _build_payload([], "m", 0.5, 50, stream=True)
    assert ps["stream"] is True
    pt = _build_payload([], "m", 0.5, 50, tools=[{"type": "function"}])
    assert pt["tools"] == [{"type": "function"}]


def test_build_payload_json_mode_deepseek():
    with patch("app.config.settings.llm_provider", "deepseek"), \
         patch("app.config.settings.deepseek_api_key", "k"), \
         patch("app.config.settings.deepseek_base_url", "https://x"), \
         patch("app.config.settings.deepseek_model", "m"):
        p = _build_payload([], "m", 0.0, 50, json_mode=True, provider="deepseek")
    assert p.get("response_format") == {"type": "json_object"}


def test_resolve_provider_uses_cache():
    with patch("app.tools.llm_tools._PROVIDER_CACHE", {}), \
         patch("app.tools.providers.provider_factory") as pf:
        prov = MagicMock()
        prov.resolve.return_value = MagicMock()
        prov.resolve.return_value.as_tuple.return_value = ("https://x", "m", "k")
        pf.return_value = prov
        assert _resolve_provider("deepseek") == ("https://x", "m", "k")
        # 第二次命中缓存，不再调 factory
        assert _resolve_provider("deepseek") == ("https://x", "m", "k")
        assert pf.call_count == 1


def test_safe_get_content_edge_cases():
    assert _safe_get_content({}) is None
    assert _safe_get_content({"choices": []}) is None
    assert _safe_get_content({"choices": [{"message": {}}]}) is None
    assert _safe_get_content({"choices": [{"message": {"content": None}}]}) is None
    assert _safe_get_content({"choices": [{"message": {"content": "ok"}}]}) == "ok"


def test_safe_get_tool_call():
    assert _safe_get_tool_call({}) is None
    assert _safe_get_tool_call({"choices": [{"message": {}}]}) is None
    assert _safe_get_tool_call({"choices": [{"message": {"tool_calls": []}}]}) is None
    tc = {"id": "1", "function": {"name": "f", "arguments": "{}"}}
    assert _safe_get_tool_call({"choices": [{"message": {"tool_calls": [tc]}}]}) == tc


def test_safe_get_usage():
    u = _safe_get_usage({"usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}})
    assert u == {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}
    assert _safe_get_usage({}) == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def test_strip_think_blocks():
    # 完整块
    assert _strip_think_blocks("你好<think>内部</think>世界", {"in_think": False, "buffer": ""}) == "你好世界"
    # 跨 chunk：末尾只有 "<"，缓存等待后续
    assert _strip_think_blocks("你好<", {"in_think": False, "buffer": ""}) == ""
    st = {"in_think": False, "buffer": "<thi"}
    out = _strip_think_blocks("nk>内部", st)
    assert out == "" and st["in_think"] is True
    out2 = _strip_think_blocks("</think>继续", st)
    assert out2 == "继续" and st["in_think"] is False
    # 超过缓冲阈值的尾巴不再缓存，直接输出
    assert _strip_think_blocks("abcdefghij<think>", {"in_think": False, "buffer": ""}) == "abcdefghij"
    assert _strip_think_blocks("普通内容", {"in_think": False, "buffer": ""}) == "普通内容"


# ─── chat_sync ───
def test_chat_sync_success():
    client = MagicMock()
    client.post.return_value = _ok_response("答案")
    with patch("app.tools.llm_tools._get_sync_client", return_value=client):
        assert LLM_tools.chat_sync([{"role": "user", "content": "q"}]) == "答案"


def test_chat_sync_non_retryable_4xx():
    resp = MagicMock()
    resp.status_code = 401
    resp.text = "unauthorized"
    resp.raise_for_status.side_effect = httpx.HTTPStatusError("401", request=MagicMock(), response=resp)
    client = MagicMock()
    client.post.return_value = resp
    with patch("app.tools.llm_tools._get_sync_client", return_value=client):
        assert LLM_tools.chat_sync([{"role": "user", "content": "q"}]) is None


def test_chat_sync_timeout():
    client = MagicMock()
    client.post.side_effect = httpx.TimeoutException("timeout")
    with patch("app.tools.llm_tools._get_sync_client", return_value=client), \
         patch("app.tools.llm_tools._RETRY_MAX_ATTEMPTS", 1):
        assert LLM_tools.chat_sync([{"role": "user", "content": "q"}]) is None


def test_chat_sync_retry_then_success():
    """429 后重试成功"""
    client = MagicMock()
    resp_fail = MagicMock()
    resp_fail.status_code = 429
    resp_fail.raise_for_status.side_effect = httpx.HTTPStatusError("429", request=MagicMock(), response=resp_fail)
    client.post.side_effect = [resp_fail, _ok_response("ok")]
    with patch("app.tools.llm_tools._get_sync_client", return_value=client), \
         patch("app.utils.task_cancel.interruptible_sleep") as sl:
        assert LLM_tools.chat_sync([{"role": "user", "content": "q"}]) == "ok"
        sl.assert_called_once()


def test_chat_sync_exhausted_retries():
    client = MagicMock()
    resp_fail = MagicMock()
    resp_fail.status_code = 503
    resp_fail.raise_for_status.side_effect = httpx.HTTPStatusError("503", request=MagicMock(), response=resp_fail)
    client.post.return_value = resp_fail
    with patch("app.tools.llm_tools._get_sync_client", return_value=client), \
         patch("app.tools.llm_tools._RETRY_MAX_ATTEMPTS", 2), \
         patch("app.utils.task_cancel.interruptible_sleep") as sl:
        assert LLM_tools.chat_sync([{"role": "user", "content": "q"}]) is None
        # attempt1 失败→sleep→attempt2 失败→raise；sleep 只 1 次
        assert sl.call_count == 1


# ─── chat_sync_json ───
def test_chat_sync_json_success_strips_codeblock_and_think():
    raw = '```json\n{"a": 1}\n```'
    client = MagicMock()
    client.post.return_value = _ok_response(raw)
    with patch("app.tools.llm_tools._get_sync_client", return_value=client), \
         patch("app.tools.llm_tools._resolve_provider", return_value=("https://x", "m", "k")):
        assert LLM_tools.chat_sync_json([{"role": "user", "content": "q"}]) == {"a": 1}


def test_chat_sync_json_returns_none_on_empty():
    client = MagicMock()
    client.post.return_value = _ok_response("")
    with patch("app.tools.llm_tools._get_sync_client", return_value=client), \
         patch("app.tools.llm_tools._resolve_provider", return_value=("https://x", "m", "k")):
        assert LLM_tools.chat_sync_json([{"role": "user", "content": "q"}]) is None


def test_chat_sync_json_minimax_prompt_prefix():
    """MiniMax 不支持 json_mode → prompt 前缀追加"""
    class FakeMiniMax:
        def supports_json_mode(self):
            return False
        def json_mode_prompt_prefix(self):
            return [{"role": "system", "content": "JSON 模式"}]
        def build_payload_extra(self, payload, json_mode=False):
            return payload
    client = MagicMock()
    client.post.return_value = _ok_response('{"b": 2}')
    with patch("app.tools.llm_tools._get_sync_client", return_value=client), \
         patch("app.tools.providers.provider_factory", return_value=FakeMiniMax()), \
         patch("app.tools.llm_tools._resolve_provider", return_value=("https://x", "m", "k")):
        assert LLM_tools.chat_sync_json([{"role": "user", "content": "q"}]) == {"b": 2}


# ─── chat_with_tools ───
def test_chat_with_tools_tool_call_parsing():
    tc = {
        "id": "call_1",
        "function": {"name": "search", "arguments": '{"q": "x"}'},
    }
    client = MagicMock()
    client.post.return_value = _ok_response("", tool_calls=[tc], usage={"total_tokens": 5})
    with patch("app.tools.llm_tools._get_tools_client", return_value=client):
        r = LLM_tools.chat_with_tools([{"role": "user", "content": "q"}], tools=[{"type": "function"}])
    assert r["tool_call"] is True
    assert r["tool_calls"][0]["tool_name"] == "search"
    assert r["tool_calls"][0]["arguments"] == {"q": "x"}
    assert r["tool_name"] == "search"
    assert r["usage"]["total_tokens"] == 5


def test_chat_with_tools_no_tool_call():
    client = MagicMock()
    client.post.return_value = _ok_response("普通回复")
    with patch("app.tools.llm_tools._get_tools_client", return_value=client):
        r = LLM_tools.chat_with_tools([{"role": "user", "content": "q"}], [])
    assert r["tool_call"] is False
    assert r["content"] == "普通回复"


def test_chat_with_tools_failure():
    client = MagicMock()
    client.post.side_effect = httpx.TimeoutException("t")
    with patch("app.tools.llm_tools._get_tools_client", return_value=client), \
         patch("app.tools.llm_tools._RETRY_MAX_ATTEMPTS", 1):
        assert LLM_tools.chat_with_tools([{"role": "user", "content": "q"}], []) is None


def test_chat_with_tools_router_provider():
    with patch.object(LLM_tools, "chat_with_tools", return_value={"tool_call": False, "content": "x", "usage": {}}) as m, \
         patch("app.config.settings.router_llm_provider", "minimax"):
        LLM_tools.chat_with_tools_router([{"role": "user", "content": "q"}], [])
    assert m.call_args.kwargs.get("provider") == "minimax"


# ─── chat_sync_typed ───
def test_chat_sync_typed_valid():
    class M(BaseModel):
        name: str
    with patch.object(LLM_tools, "chat_sync_json", return_value={"name": "x"}):
        assert LLM_tools.chat_sync_typed([], M).name == "x"


def test_chat_sync_typed_self_correction():
    class M(BaseModel):
        num: int
    calls = [{"num": "bad"}, {"num": 42}]
    with patch.object(LLM_tools, "chat_sync_json", side_effect=calls):
        assert LLM_tools.chat_sync_typed([], M, max_validation_retries=3).num == 42


def test_chat_sync_typed_exhausts_returns_none():
    class M(BaseModel):
        num: int
    with patch.object(LLM_tools, "chat_sync_json", return_value={"num": "bad"}):
        assert LLM_tools.chat_sync_typed([], M, max_validation_retries=1) is None


def test_chat_sync_typed_none_raw():
    class M(BaseModel):
        a: str
    with patch.object(LLM_tools, "chat_sync_json", return_value=None):
        assert LLM_tools.chat_sync_typed([], M, max_validation_retries=1) is None


# ─── stream_chat ───
def test_stream_chat_collects_content_and_think_filter():
    async def run():
        chunks = []
        client = _stream_ctx([
            "data: " + __import__("json").dumps({"choices": [{"delta": {"content": "你"}}]}),
            "data: " + __import__("json").dumps({"choices": [{"delta": {"content": "<think>推理"}}]}),
            "data: " + __import__("json").dumps({"choices": [{"delta": {"content": "</think>好"}}]}),
            "data: [DONE]",
        ])
        with patch("app.tools.llm_tools._get_async_client", return_value=client):
            async for c in LLM_tools.stream_chat([{"role": "user", "content": "q"}]):
                chunks.append(c)
        return chunks

    out = asyncio.run(run())
    assert "你" in out
    assert "推理" not in out
    assert "好" in out


def test_stream_chat_4xx_yields_unavailable():
    async def run():
        client = _stream_ctx([], status_code=404, body=b"not found")
        with patch("app.tools.llm_tools._get_async_client", return_value=client):
            out = [c async for c in LLM_tools.stream_chat([{"role": "user", "content": "q"}])]
        return out

    out = asyncio.run(run())
    assert out  # 4xx 返回 LLM_UNAVAILABLE_MSG（中文兜底文案）


def test_stream_chat_retry_connect_error_then_success():
    async def run():
        bad = MagicMock()
        bad.stream.side_effect = httpx.ConnectError("down")
        good = _stream_ctx([
            "data: " + __import__("json").dumps({"choices": [{"delta": {"content": "ok"}}]}),
            "data: [DONE]",
        ])
        calls = {"n": 0}
        def _fake_get():
            calls["n"] += 1
            return bad if calls["n"] == 1 else good
        with patch("app.tools.llm_tools._get_async_client", side_effect=_fake_get), \
             patch("app.tools.llm_tools._RETRY_MAX_ATTEMPTS", 2), \
             patch("asyncio.sleep", return_value=None) as sl:
            out = [c async for c in LLM_tools.stream_chat([{"role": "user", "content": "q"}])]
        return out, sl

    out, sl = asyncio.run(run())
    assert "ok" in out
    sl.assert_awaited_once()


# ─── vision messages ───
def test_build_vision_messages():
    msgs = [{"role": "user", "content": "看图"}]
    out = LLM_tools._build_vision_messages(msgs, ["http://a/1.jpg"])
    assert out[0]["role"] == "user"
    assert isinstance(out[0]["content"], list)
    assert out[0]["content"][1]["type"] == "image_url"
    # 无图片时原样返回
    assert LLM_tools._build_vision_messages(msgs, []) == msgs


# ─── embedding ───
def test_embed_hash_fallback():
    with patch.object(LLM_tools, "_get_embed_model", return_value=_HashEmbedder()):
        vecs = LLM_tools.embed(["hello world", "hello"])
    assert vecs is not None
    assert len(vecs) == 2
    assert len(vecs[0]) == 384


def test_embed_returns_none_when_model_none():
    with patch.object(LLM_tools, "_get_embed_model", return_value=None):
        assert LLM_tools.embed(["x"]) is None


def test_embed_failure_returns_none():
    class BadModel:
        def encode(self, texts):
            raise RuntimeError("boom")
    with patch.object(LLM_tools, "_get_embed_model", return_value=BadModel()):
        assert LLM_tools.embed(["x"]) is None


def test_get_embed_model_caches_and_falls_back_to_hash():
    LLM_tools._embed_model = None
    patches = [patch("app.tools.fastembed_embeddings.FastEmbedEmbeddings", side_effect=Exception("no onnx"))]
    try:
        # sentence_transformers 可能未安装；装了也一样 patch 成抛错，确保走 hash fallback
        patches.append(patch("sentence_transformers.SentenceTransformer", side_effect=Exception("no torch")))
    except ModuleNotFoundError:
        pass
    with patches[0]:
        model = LLM_tools._get_embed_model()
    assert isinstance(model, _HashEmbedder)
    assert LLM_tools._get_embed_model() is model  # 命中缓存
    LLM_tools._embed_model = None


# ─── abortable clients / close ───
def test_abortable_http_client_registers_close():
    import threading

    from app.utils.task_cancel import abort_running_io, cancel_scope
    ev = threading.Event()
    closed = []
    with cancel_scope(ev):
        client = MagicMock()
        client.is_closed = False
        def _close():
            closed.append(1)
            client.is_closed = True
        client.close = _close
        with patch("app.tools.llm_tools._new_sync_client", return_value=client):
            got = _abortable_http_client("sync")
        assert got is client
        abort_running_io(ev)
    assert closed == [1]


def test_abortable_http_client_no_scope_returns_none():
    assert _abortable_http_client("sync") is None


def test_close_http_clients_clears_globals():
    from app.tools.llm_tools import _sync_client, _tools_client
    close_http_clients()
    assert _sync_client is None and _tools_client is None


def test_aclose_async_client():
    async def run():
        await aclose_async_client()
    asyncio.run(run())


# ─── call_with_retry_sync ───
def test_call_with_retry_non_retryable_raises():
    def bad(attempt):
        resp = MagicMock()
        resp.status_code = 400
        raise httpx.HTTPStatusError("400", request=MagicMock(), response=resp)
    with pytest.raises(httpx.HTTPStatusError):
        _call_with_retry_sync(bad, "op")


def test_call_with_retry_connect_error():
    def bad(attempt):
        raise httpx.ConnectError("down")
    with patch("app.tools.llm_tools._RETRY_MAX_ATTEMPTS", 2), \
         patch("app.utils.task_cancel.interruptible_sleep") as sl:
        with pytest.raises(httpx.ConnectError):
            _call_with_retry_sync(bad, "op")
        assert sl.call_count == 1


def test_call_with_retry_cancelled_raises():
    import threading

    from app.utils.task_cancel import WorkflowCancelled, cancel_scope
    ev = threading.Event()
    def bad(attempt):
        raise WorkflowCancelled()
    with cancel_scope(ev):
        with pytest.raises(WorkflowCancelled):
            _call_with_retry_sync(bad, "op")

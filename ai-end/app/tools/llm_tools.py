import asyncio
import json
import logging
import threading
import time
from typing import Any, AsyncIterator, Dict, List, Optional, Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.tools.output_guard import LLM_UNAVAILABLE_MSG

# ─── 复用型 httpx Client（keep-alive，节省 TCP/TLS 握手） ───
# 每个请求新建 client 每次都要握手 ~30-100ms（生产更慢）。
# 进程级单例 + pool 连接数与 db_pool 对齐。
_client_lock = threading.Lock()
_sync_client: Optional[httpx.Client] = None
_tools_client: Optional[httpx.Client] = None
_async_client: Optional[httpx.AsyncClient] = None
_async_client_loop_id: Optional[int] = None


def _get_async_client() -> httpx.AsyncClient:
    """异步流式 LLM 调用的复用 client（带 keep-alive + 连接池）"""
    global _async_client, _async_client_loop_id
    # 检查当前 event loop 是否变化（测试或多 loop 场景）
    try:
        current_loop = asyncio.get_running_loop()
        current_loop_id = id(current_loop)
    except RuntimeError:
        current_loop_id = None
    cached_loop_id = _async_client_loop_id if '_async_client_loop_id' in globals() else None
    if _async_client is None or cached_loop_id != current_loop_id:
        with _client_lock:
            cached_loop_id = _async_client_loop_id if '_async_client_loop_id' in globals() else None
            if _async_client is None or cached_loop_id != current_loop_id:
                _async_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(60.0, connect=10.0, read=60.0),
                    limits=httpx.Limits(
                        max_connections=settings.db_pool_size,
                        max_keepalive_connections=settings.db_pool_size // 2 or 1,
                    ),
                )
                _async_client_loop_id = current_loop_id
    return _async_client


def _get_sync_client() -> httpx.Client:
    global _sync_client
    if _sync_client is None:
        with _client_lock:
            if _sync_client is None:
                _sync_client = httpx.Client(
                    timeout=httpx.Timeout(30.0, connect=10.0, read=30.0),
                    limits=httpx.Limits(
                        max_connections=settings.db_pool_size,
                        max_keepalive_connections=settings.db_pool_size // 2 or 1,
                    ),
                )
    return _sync_client


def _get_tools_client() -> httpx.Client:
    global _tools_client
    if _tools_client is None:
        with _client_lock:
            if _tools_client is None:
                _tools_client = httpx.Client(
                    timeout=httpx.Timeout(15.0, connect=10.0, read=15.0),
                    limits=httpx.Limits(
                        max_connections=max(settings.db_pool_size, 16),
                        max_keepalive_connections=8,
                    ),
                )
    return _tools_client


async def aclose_async_client():
    """异步关闭复用 AsyncClient（main.py lifespan 里 await 调用，避免新起线程）。"""
    global _async_client, _async_client_loop_id
    if _async_client is not None:
        try:
            await _async_client.aclose()
        except Exception as e:
            logger.debug(f"AsyncClient 关闭异常: {e}")
    _async_client = None
    _async_client_loop_id = None


def close_http_clients():
    """Graceful shutdown：关闭同步复用连接池（AsyncClient 由 aclose_async_client 处理）。"""
    global _sync_client, _tools_client
    for c in (_sync_client, _tools_client):
        if c is not None:
            try:
                c.close()
            except Exception:
                pass
    _sync_client = None
    _tools_client = None

try:
    from app.utils.metrics import llm_requests_total, llm_token_usage
    _METRICS_AVAILABLE = True
except ImportError:
    _METRICS_AVAILABLE = False

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def _record_llm_metrics(operation: str, provider: str, status: str, usage: Dict[str, int] = None):
    """记录 LLM 调用指标到 Prometheus"""
    if not _METRICS_AVAILABLE:
        return
    llm_requests_total.labels(operation=operation, provider=provider, status=status).inc()
    if usage:
        for token_type in ("prompt_tokens", "completion_tokens", "total_tokens"):
            val = usage.get(token_type, 0)
            if val > 0:
                llm_token_usage.labels(provider=provider, type=token_type).inc(val)


# ─── 可重试异常分类 ───
# 这些错误可以重试（网络抖动、限流、服务端临时错误）
_RETRYABLE_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}
_RETRY_MAX_ATTEMPTS = settings.llm_retry_max_attempts
_RETRY_BASE_DELAY = settings.llm_retry_base_delay
_RETRY_MAX_DELAY = settings.llm_retry_max_delay


def _is_retryable_http_status(status_code: int) -> bool:
    return status_code in _RETRYABLE_HTTP_STATUSES


def _strip_think_blocks(chunk: str, state: Dict[str, Any]) -> str:
    """
    流式过滤 MiniMax-M3 等推理模型的 <think>...</think> 块。
    跨 chunk 时用 state["buffer"] 暂存未决的部分，保证边界正确。
    state: {"in_think": bool, "buffer": str}
    返回过滤后的可输出片段（可能为空）。
    """
    text = state["buffer"] + chunk
    state["buffer"] = ""
    output_parts = []
    i = 0
    while i < len(text):
        if state["in_think"]:
            end_idx = text.find("</think>", i)
            if end_idx == -1:
                # 还在 think 块内，丢弃，等待后续 chunk
                state["buffer"] = ""
                return ""
            else:
                state["in_think"] = False
                i = end_idx + len("</think>")
                continue
        else:
            start_idx = text.find("<think>", i)
            if start_idx == -1:
                # 没有 think 起始，剩余部分可能是不完整的标签
                tail = text[i:]
                if tail.endswith("<") or tail.endswith("<think>") or "<think" in tail[-6:] or "<th" in tail[-3:]:
                    # 可能是跨 chunk 的标签开头，缓存
                    state["buffer"] = tail
                    if len(tail) > 8:
                        state["buffer"] = ""
                        return tail
                    return ""
                output_parts.append(text[i:])
                state["buffer"] = ""
                return "".join(output_parts)
            else:
                output_parts.append(text[i:start_idx])
                state["in_think"] = True
                i = start_idx + len("<think>")
    # 正常结束
    state["buffer"] = ""
    return "".join(output_parts)


def _safe_get_content(data: dict) -> Optional[str]:
    choices = data.get("choices")
    if not choices or not isinstance(choices, list) or len(choices) == 0:
        logger.error("LLM 返回异常: choices 为空或非列表")
        return None
    message = choices[0].get("message", {})
    if not message:
        logger.error("LLM 返回异常: message 为空")
        return None
    content = message.get("content")
    if content is None:
        logger.warning("LLM 返回内容为空")
    return content


def _safe_get_tool_call(data: dict) -> Optional[dict]:
    choices = data.get("choices")
    if not choices or not isinstance(choices, list) or len(choices) == 0:
        logger.error("LLM tool_call 返回异常: choices 为空")
        return None
    message = choices[0].get("message", {})
    if not message:
        return None
    tool_calls = message.get("tool_calls", [])
    if not tool_calls or not isinstance(tool_calls, list) or len(tool_calls) == 0:
        return None
    return tool_calls[0]


def _safe_get_usage(data: dict) -> Dict[str, int]:
    """提取 token usage，用于成本追踪"""
    usage = data.get("usage") or {}
    return {
        "prompt_tokens": int(usage.get("prompt_tokens", 0)),
        "completion_tokens": int(usage.get("completion_tokens", 0)),
        "total_tokens": int(usage.get("total_tokens", 0)),
    }


_PROVIDER_CACHE: Dict[str, tuple] = {}


def _resolve_provider(provider: Optional[str] = None) -> tuple:
    """
    解析 LLM provider 配置。返回 (base_url, model, api_key) 三元组。

    不再读写全局 settings.llm_provider——所有调用方通过参数显式传，
    避免多线程下"router 用 A 模型、普通用 B 模型"的串台 bug。

    缓存：(provider) → (base_url, model, api_key)
    每次 LLM 调用都做 settings.xxx 属性读取会触发 Pydantic __getattr__，
    缓存元组后省掉这部分开销。
    """
    p = provider or settings.llm_provider
    cached = _PROVIDER_CACHE.get(p)
    if cached is not None:
        return cached
    from app.tools.providers import provider_factory
    result = provider_factory(p).resolve().as_tuple()
    _PROVIDER_CACHE[p] = result
    return result


def _get_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _build_payload(messages: List[Dict[str, str]], model: str, temperature: float = 0.7,
                   max_tokens: int = 2000, stream: bool = False,
                   tools: List[Dict] = None, json_mode: bool = False,
                   provider: Optional[str] = None) -> dict:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if stream:
        payload["stream"] = True
    if tools:
        payload["tools"] = tools
    if json_mode:
        # 是否支持 OpenAI response_format=json_object 由 provider 决定
        # （minimax 不支持，改用 prompt 指令约束，见 chat_sync_json）
        from app.tools.providers import provider_factory
        prov_obj = provider_factory(provider or settings.llm_provider)
        payload = prov_obj.build_payload_extra(payload, json_mode=True)
    return payload


def _call_with_retry_sync(call_fn, op_name: str):
    """
    同步 LLM 调用的指数退避包装。
    - 仅对 429/5xx/timeout 重试
    - 4xx（除 429）不重试
    - 最多 _RETRY_MAX_ATTEMPTS 次
    """
    last_exc = None
    for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
        try:
            return call_fn(attempt)
        except httpx.HTTPStatusError as e:
            last_exc = e
            status = e.response.status_code
            if not _is_retryable_http_status(status):
                logger.error(f"{op_name} 失败 (status={status})，非可重试错误，直接返回")
                raise
            if attempt >= _RETRY_MAX_ATTEMPTS:
                logger.error(f"{op_name} 失败 (status={status})，已达最大重试次数 {attempt}/{_RETRY_MAX_ATTEMPTS}")
                raise
            delay = min(_RETRY_BASE_DELAY * (2 ** (attempt - 1)), _RETRY_MAX_DELAY)
            logger.warning(f"{op_name} 失败 (status={status})，{delay:.1f}s 后第 {attempt+1} 次重试")
            time.sleep(delay)
        except httpx.TimeoutException as e:
            last_exc = e
            if attempt >= _RETRY_MAX_ATTEMPTS:
                logger.error(f"{op_name} 超时，已达最大重试次数 {attempt}/{_RETRY_MAX_ATTEMPTS}")
                raise
            delay = min(_RETRY_BASE_DELAY * (2 ** (attempt - 1)), _RETRY_MAX_DELAY)
            logger.warning(f"{op_name} 超时，{delay:.1f}s 后第 {attempt+1} 次重试")
            time.sleep(delay)
        except (httpx.ConnectError, httpx.RemoteProtocolError) as e:
            last_exc = e
            if attempt >= _RETRY_MAX_ATTEMPTS:
                logger.error(f"{op_name} 连接错误，已达最大重试次数 {attempt}/{_RETRY_MAX_ATTEMPTS}")
                raise
            delay = min(_RETRY_BASE_DELAY * (2 ** (attempt - 1)), _RETRY_MAX_DELAY)
            logger.warning(f"{op_name} 连接错误，{delay:.1f}s 后第 {attempt+1} 次重试")
            time.sleep(delay)
    if last_exc:
        raise last_exc
    return None


class _HashEmbedder:
    """
    兜底 embedding：当 sentence_transformers 不可用时使用。
    基于哈希 + 数学归一化生成 384 维向量。**仅用于服务启动和测试**，不用于生产。
    接口兼容：model.encode([text]) -> ndarray of shape (n, dim)
    """
    def __init__(self, dim: int = 384):
        self.dim = dim

    def encode(self, texts):
        import hashlib
        import math

        import numpy as np
        results = []
        for text in texts:
            v = np.zeros(self.dim, dtype=np.float32)
            tokens = [t for t in text.split() if t]
            if not tokens:
                results.append(v)
                continue
            for tok in tokens:
                h = hashlib.md5(tok.encode("utf-8")).digest()
                for i in range(0, len(h), 4):
                    idx = int.from_bytes(h[i:i+4], "big") % self.dim
                    sign = 1.0 if (h[i // 4] & 1) else -1.0
                    v[idx] += sign * (1.0 / math.sqrt(len(tokens)))
            norm = np.linalg.norm(v)
            if norm > 0:
                v = v / norm
            results.append(v)
        return np.stack(results)


class LLM_tools:
    _embed_model = None
    _embed_lock = threading.Lock()

    @staticmethod
    async def chat(messages: List[Dict[str, str]], temperature: float = 0.7,
                   max_tokens: int = 2000, provider: Optional[str] = None) -> Optional[str]:
        base_url, model, api_key = _resolve_provider(provider)
        payload = _build_payload(messages, model, temperature, max_tokens)
        headers = _get_headers(api_key)

        last_exc = None
        for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
            try:
                client = _get_async_client()
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                return _safe_get_content(data) or ""
            except httpx.HTTPStatusError as e:
                last_exc = e
                if not _is_retryable_http_status(e.response.status_code):
                    logger.error(f"LLM.chat 失败 (status={e.response.status_code})，非可重试")
                    return None
            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as e:
                last_exc = e
            if attempt >= _RETRY_MAX_ATTEMPTS:
                break
            delay = min(_RETRY_BASE_DELAY * (2 ** (attempt - 1)), _RETRY_MAX_DELAY)
            logger.warning(f"LLM.chat 第 {attempt} 次失败，{delay:.1f}s 后重试 (err={last_exc})")
            await asyncio.sleep(delay)
        logger.error(f"LLM.chat 全部重试失败: {last_exc}")
        return None

    @staticmethod
    def chat_sync(messages: List[Dict[str, str]], temperature: float = 0.7,
                  max_tokens: int = 2000, provider: Optional[str] = None) -> Optional[str]:
        base_url, model, api_key = _resolve_provider(provider)
        prov = provider or settings.llm_provider

        def _do(attempt: int) -> str:
            client = _get_sync_client()
            response = client.post(
                f"{base_url}/chat/completions",
                headers=_get_headers(api_key),
                json=_build_payload(messages, model, temperature, max_tokens),
            )
            response.raise_for_status()
            data = response.json()
            usage = _safe_get_usage(data)
            _record_llm_metrics("chat_sync", prov, "success", usage)
            return _safe_get_content(data) or ""

        try:
            return _call_with_retry_sync(_do, "LLM.chat_sync")
        except httpx.HTTPStatusError as e:
            _record_llm_metrics("chat_sync", prov, "error")
            logger.error(f"LLM同步调用失败 {e.response.status_code}: {e.response.text[:200]}")
            return None
        except httpx.TimeoutException:
            _record_llm_metrics("chat_sync", prov, "timeout")
            logger.error("LLM调用超时")
            return None
        except Exception as e:
            _record_llm_metrics("chat_sync", prov, "error")
            logger.error(f"LLM同步调用失败: {e}")
            return None

    @staticmethod
    def chat_sync_with_usage(messages: List[Dict[str, str]], temperature: float = 0.7,
                             max_tokens: int = 2000, provider: Optional[str] = None):
        """同步聊天并返回 (content, usage)。用于需要精确 token 计数的场景（如 compact 摘要）。"""
        base_url, model, api_key = _resolve_provider(provider)
        prov = provider or settings.llm_provider

        def _do(attempt: int):
            client = _get_sync_client()
            response = client.post(
                f"{base_url}/chat/completions",
                headers=_get_headers(api_key),
                json=_build_payload(messages, model, temperature, max_tokens),
            )
            response.raise_for_status()
            data = response.json()
            usage = _safe_get_usage(data)
            _record_llm_metrics("chat_sync_with_usage", prov, "success", usage)
            content = _safe_get_content(data) or ""
            return content, usage

        try:
            return _call_with_retry_sync(_do, "LLM.chat_sync_with_usage")
        except Exception as e:
            _record_llm_metrics("chat_sync_with_usage", prov, "error")
            logger.error(f"LLM同步调用(带 usage)失败: {e}")
            return None

    @staticmethod
    def _build_vision_messages(messages: List[Dict[str, str]], image_urls: List[str]) -> List[Dict]:
        """将最后一条 user 消息转为多模态格式（OpenAI 兼容）"""
        if not image_urls:
            return messages
        result = list(messages)
        for i in range(len(result) - 1, -1, -1):
            if result[i].get("role") == "user":
                content_parts = [{"type": "text", "text": result[i]["content"]}]
                for url in image_urls:
                    content_parts.append({"type": "image_url", "image_url": {"url": url}})
                result[i] = {"role": "user", "content": content_parts}
                break
        return result

    @staticmethod
    async def stream_chat(messages: List[Dict[str, str]], temperature: float = 0.7,
                          max_tokens: int = 2000, image_urls: List[str] = None,
                          provider: Optional[str] = None) -> AsyncIterator[str]:
        """
        流式 LLM 调用。带 retry（指数退避）+ 复用 AsyncClient。

        重试策略：
        - 仅在连接建立失败 / 5xx / 429 时重试
        - 已经拿到流的部分（HTTP 200 + 数据到达）不重试，避免重复内容
        - 最多 _RETRY_MAX_ATTEMPTS 次
        """
        base_url, model, api_key = _resolve_provider(provider)
        msgs = LLM_tools._build_vision_messages(messages, image_urls or [])
        payload = _build_payload(msgs, model, temperature, max_tokens, stream=True)
        # 状态机：跟踪 <think>...</think> 块边界，避免跨 chunk 时漏过滤
        think_state = {"in_think": False, "buffer": ""}
        headers = _get_headers(api_key)

        last_exc: Optional[Exception] = None
        for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
            try:
                client = _get_async_client()
                async with client.stream(
                    "POST",
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                ) as response:
                    # 状态码非 2xx 视为可重试
                    if response.status_code >= 500 or response.status_code == 429:
                        raise httpx.HTTPStatusError(
                            f"server error {response.status_code}",
                            request=response.request,
                            response=response,
                        )
                    if response.status_code >= 400:
                        # 4xx 不重试，直接抛
                        body = await response.aread()
                        logger.error(f"stream_chat 4xx 错误 {response.status_code}: {body[:200]}")
                        yield LLM_UNAVAILABLE_MSG
                        return
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                return
                            try:
                                data = json.loads(data_str)
                                choices = data.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    content = delta.get("content", "")
                                    if content:
                                        # 过滤 MiniMax-M3 等推理模型的 <think>...</think> 块
                                        content = _strip_think_blocks(content, think_state)
                                        if content:
                                            yield content
                            except json.JSONDecodeError:
                                continue
                    # 正常结束
                    return
            except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.HTTPStatusError, httpx.TimeoutException) as e:
                last_exc = e
                if attempt >= _RETRY_MAX_ATTEMPTS:
                    break
                delay = min(_RETRY_BASE_DELAY * (2 ** (attempt - 1)), _RETRY_MAX_DELAY)
                logger.warning(f"stream_chat 第 {attempt} 次失败，{delay:.1f}s 后重试 (err={e})")
                await asyncio.sleep(delay)
            except Exception as e:
                # 其他异常不重试
                logger.error(f"stream_chat 异常: {e}", exc_info=True)
                yield LLM_UNAVAILABLE_MSG
                return
        logger.error(f"stream_chat 全部重试失败: {last_exc}")
        yield LLM_UNAVAILABLE_MSG

    @staticmethod
    def chat_with_tools(messages: List[Dict[str, str]], tools: List[Dict],
                        temperature: float = 0.0, max_tokens: int = 500,
                        provider: Optional[str] = None) -> Optional[Dict]:
        """
        Function Calling 调用。

        provider 参数（修复 race condition）：
        - 不再修改全局 settings.llm_provider
        - 调用方显式指定要走哪个 provider
        - 多线程并发时不会互相覆盖
        """
        base_url, model, api_key = _resolve_provider(provider)
        prov = provider or settings.llm_provider

        def _do(attempt: int) -> Dict:
            client = _get_tools_client()
            response = client.post(
                f"{base_url}/chat/completions",
                headers=_get_headers(api_key),
                json=_build_payload(messages, model, temperature, max_tokens, tools=tools),
            )
            response.raise_for_status()
            data = response.json()
            content = _safe_get_content(data) or ""
            usage = _safe_get_usage(data)
            _record_llm_metrics("chat_with_tools", prov, "success", usage)
            tool_call = _safe_get_tool_call(data)
            if tool_call:
                # 合并所有 tool_calls（支持多函数并行调用）
                all_tool_calls = data.get("choices", [{}])[0].get("message", {}).get("tool_calls", [])
                parsed_calls = []
                for tc in all_tool_calls:
                    raw_args = tc["function"]["arguments"]
                    if isinstance(raw_args, str):
                        try:
                            args = json.loads(raw_args)
                        except json.JSONDecodeError:
                            logger.warning(f"tool_call arguments 解析失败: {raw_args[:200]}")
                            args = {}
                    elif isinstance(raw_args, dict):
                        args = raw_args
                    else:
                        args = {}
                    parsed_calls.append({
                        "tool_call_id": tc.get("id", tc["function"]["name"]),
                        "tool_name": tc["function"]["name"],
                        "arguments": args,
                    })
                return {
                    "tool_call": True,
                    "tool_calls": parsed_calls,  # 改：返回列表（不只是第一个）
                    "tool_call_id": parsed_calls[0]["tool_call_id"],  # 向后兼容
                    "tool_name": parsed_calls[0]["tool_name"],
                    "arguments": parsed_calls[0]["arguments"],
                    "content": content,
                    "usage": usage,
                }
            return {
                "tool_call": False,
                "content": content,
                "usage": usage,
            }

        try:
            return _call_with_retry_sync(_do, "LLM.chat_with_tools")
        except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError) as e:
            _record_llm_metrics("chat_with_tools", prov, "error")
            logger.error(f"LLM Function Calling 调用失败: {e}")
            return None
        except Exception as e:
            _record_llm_metrics("chat_with_tools", prov, "error")
            logger.error(f"LLM Function Calling 调用失败: {e}")
            return None

    @staticmethod
    def chat_sync_json(messages: List[Dict[str, str]], temperature: float = 0.0,
                       max_tokens: int = 4000, timeout: float = 30.0,
                       provider: Optional[str] = None) -> Optional[Dict]:
        base_url, model, api_key = _resolve_provider(provider)
        prov = provider or settings.llm_provider

        # 不支持 response_format 的 provider（如 minimax）在 prompt 里追加 JSON 指令
        msgs = list(messages)
        from app.tools.providers import provider_factory
        prov_obj = provider_factory(prov)
        if not prov_obj.supports_json_mode():
            prefix = getattr(prov_obj, "json_mode_prompt_prefix", None)
            if prefix:
                msgs = list(prefix()) + msgs

        def _do(attempt: int) -> Dict:
            client = _get_sync_client()
            response = client.post(
                f"{base_url}/chat/completions",
                headers=_get_headers(api_key),
                json=_build_payload(msgs, model, temperature, max_tokens, json_mode=True, provider=prov),
            )
            response.raise_for_status()
            data = response.json()
            content = _safe_get_content(data)
            if content:
                content = content.strip()
                # 去掉 markdown 代码块包裹
                if content.startswith("```"):
                    lines = content.split("\n")
                    content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
                # 去掉 MiniMax-M3 等推理模型的 <think>...</think> 痕迹
                import re as _re
                content = _re.sub(r"<think>.*?</think>\s*", "", content, flags=_re.DOTALL).strip()
                return json.loads(content)
            return None

        try:
            return _call_with_retry_sync(_do, "LLM.chat_sync_json")
        except Exception as e:
            logger.error(f"LLM JSON调用失败: {e}")
            return None

    @staticmethod
    def chat_sync_typed(
        messages: List[Dict[str, str]],
        model: Type[T],
        temperature: float = 0.0,
        max_tokens: int = 2000,
        timeout: float = 30.0,
        max_validation_retries: int = 2,
        provider: Optional[str] = None,
    ) -> Optional[T]:
        """
        调用 LLM 并按 Pydantic model 校验输出。

        Self-correction 流程：
        1. 调 LLM（json_mode）拿到字典
        2. 用 Pydantic model 校验
        3. 校验失败 → 把 ValidationError 信息塞回 prompt → 让 LLM 改 → 重试
        4. 超过 max_validation_retries → 返回 None
        """
        current_messages = list(messages)
        for attempt in range(1, max_validation_retries + 2):  # 1 初次 + N 次修正
            raw = LLM_tools.chat_sync_json(
                current_messages, temperature=temperature,
                max_tokens=max_tokens, timeout=timeout, provider=provider,
            )
            if raw is None:
                if attempt > max_validation_retries:
                    return None
                continue
            try:
                return model.model_validate(raw)
            except ValidationError as e:
                logger.warning(
                    f"Pydantic 校验失败 (attempt {attempt}/{max_validation_retries+1}): {e}"
                )
                if attempt > max_validation_retries:
                    return None
                # Self-correction：把错误塞回 prompt
                error_summary = "; ".join(
                    f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}"
                    for err in e.errors()[:5]
                )
                current_messages = current_messages + [{
                    "role": "user",
                    "content": (
                        f"你的输出不符合要求的 JSON schema，错误如下：\n{error_summary}\n"
                        f"请严格按照原始 schema 重新输出。"
                    ),
                }]
        return None

    # ─────────────────────────────────────────────
    # 路由器专用入口：不再修改全局 settings
    # ─────────────────────────────────────────────
    @classmethod
    def chat_with_tools_router(cls, messages: List[Dict[str, str]], tools: List[Dict],
                                temperature: float = 0.0, max_tokens: int = 500) -> Optional[Dict]:
        """
        路由器意图分类专用。走 router_llm_provider；留空则跟随 llm_provider。

        修复：原来会改全局 settings.llm_provider 造成 race condition；
        现在通过 provider 参数显式传入，零共享状态。
        """
        return cls.chat_with_tools(
            messages, tools, temperature, max_tokens,
            provider=settings.router_llm_provider or settings.llm_provider,
        )

    @classmethod
    def _get_embed_model(cls):
        if cls._embed_model is not None:
            return cls._embed_model
        with cls._embed_lock:
            if cls._embed_model is not None:
                return cls._embed_model
            # 1. FastEmbed（ONNX 轻量，无需 PyTorch，本地模型）
            try:
                from app.tools.fastembed_embeddings import FastEmbedEmbeddings
                cls._embed_model = FastEmbedEmbeddings()
                logger.info("Embedding 模型加载完成（FastEmbed / ONNX）")
                return cls._embed_model
            except Exception as e:
                logger.debug(f"加载 FastEmbed 失败: {e}")
            # 2. sentence-transformers（有 PyTorch 环境时）
            try:
                from sentence_transformers import SentenceTransformer
                cls._embed_model = SentenceTransformer(settings.embed_model_name)
                logger.info("Embedding 模型加载完成（sentence-transformers）")
                return cls._embed_model
            except Exception as e:
                logger.debug(f"加载 sentence_transformers 失败: {e}")
            # 3. Hash fallback（兜底）
            logger.warning("Embedding 降级到 hash-based fallback")
            cls._embed_model = _HashEmbedder(dim=384)
        return cls._embed_model

    @classmethod
    def warmup_embedding(cls, timeout: float = 30.0) -> bool:
        """
        启动期预热 Embedding 模型。

        收益：避免首请求冷启动（模型加载 + warmup 通常 5-15s）。
        失败不抛异常——预热失败应让首请求重试，而不是阻塞启动。

        timeout：超过这个时间就放弃预热（首请求仍会触发加载）。
        """
        try:
            import signal

            class _TimeoutError(Exception):
                pass

            def _alarm_handler(signum, frame):
                raise _TimeoutError("warmup timeout")

            old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
            signal.alarm(int(timeout))
            try:
                model = cls._get_embed_model()
                if model is None:
                    logger.warning("Embedding 预热跳过：模型加载失败")
                    return False
                _ = model.encode(["warmup"])
                logger.info("Embedding 模型预热完成")
                return True
            except _TimeoutError:
                logger.warning(f"Embedding 预热超时（>{timeout}s），跳过；首请求会触发加载")
                return False
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
        except Exception as e:
            # signal 在非 Unix 系统不可用——降级到不带超时
            logger.debug(f"Embedding 预热（无超时模式）异常: {e}")
            try:
                model = cls._get_embed_model()
                if model is None:
                    return False
                _ = model.encode(["warmup"])
                logger.info("Embedding 模型预热完成（无超时模式）")
                return True
            except Exception as e2:
                logger.warning(f"Embedding 预热失败: {e2}")
                return False

    @classmethod
    def embed(cls, texts: List[str]) -> Optional[List[List[float]]]:
        try:
            model = cls._get_embed_model()
            if model is None:
                return None
            embeddings = model.encode(texts)
            return embeddings.tolist()
        except Exception as e:
            logger.error(f"Embedding失败: {e}")
            return None

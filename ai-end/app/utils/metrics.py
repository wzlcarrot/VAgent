"""
Prometheus Metrics 模块

提供系统可观测性，支持监控告警。

使用方式:
    from app.utils.metrics import llm_latency, llm_token_usage

    with llm_latency.labels(operation="chat", provider="deepseek").time():
        result = call_llm()
"""

import time
from contextlib import contextmanager
from typing import Generator, Optional

from fastapi import APIRouter, Response

try:
    from prometheus_client import (
        Counter,
        Histogram,
        Gauge,
        Summary,
        Info,
        generate_latest,
        CONTENT_TYPE_LATEST,
        REGISTRY,
    )

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False


# ─── LLM 指标 ───

if PROMETHEUS_AVAILABLE:
    # LLM 请求延迟
    llm_latency = Histogram(
        "llm_request_duration_seconds",
        "LLM request latency in seconds",
        ["operation", "provider"],
        buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
    )

    # LLM Token 使用量
    llm_token_usage = Counter(
        "llm_token_usage_total",
        "Total LLM token usage",
        ["provider", "type"],  # type: prompt/completion/total
    )

    # LLM 调用次数
    llm_requests_total = Counter(
        "llm_requests_total",
        "Total LLM requests",
        ["operation", "provider", "status"],  # status: success/error/timeout
    )

    # ─── 工具调用指标 ───

    tool_call_latency = Histogram(
        "tool_call_duration_seconds",
        "Tool call latency in seconds",
        ["tool_name", "agent"],
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    )

    tool_calls_total = Counter(
        "tool_calls_total",
        "Total tool calls",
        ["tool_name", "agent", "status"],  # status: success/timeout/rejected/limit_exceeded
    )

    # ─── Router 指标 ───

    router_latency = Histogram(
        "router_duration_seconds",
        "Router decision latency in seconds",
        ["method"],  # method: keyword/semantic/llm/hybrid
        buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0),
    )

    router_decisions_total = Counter(
        "router_decisions_total",
        "Total router decisions",
        ["intent", "method"],  # intent: video_qa/recommend/user_data/chat
    )

    # ─── Workflow 指标 ───

    workflow_latency = Histogram(
        "workflow_duration_seconds",
        "Workflow execution latency in seconds",
        ["workflow_type"],
        buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
    )

    workflow_steps_total = Counter(
        "workflow_steps_total",
        "Total workflow step executions",
        ["workflow_type", "step", "status"],  # status: success/failed
    )

    # ─── Checkpoint 指标 ───

    checkpoint_operations_total = Counter(
        "checkpoint_operations_total",
        "Total checkpoint operations",
        ["operation", "status"],  # operation: save/load/clear; status: success/failed
    )

    # ─── 系统指标 ───

    active_sessions = Gauge(
        "active_sessions",
        "Number of active sessions"
    )

    redis_connection_status = Gauge(
        "redis_connection_status",
        "Redis connection status (1=connected, 0=disconnected)"
    )

    db_connection_pool_size = Gauge(
        "db_connection_pool_size",
        "Database connection pool size",
        ["state"],  # state: active/idle
    )

    # ─── 上下文压缩指标 ───

    compact_operations_total = Counter(
        "compact_operations_total",
        "Total context compact operations",
        ["status"],  # status: success/failed
    )

    compact_tokens_saved_total = Counter(
        "compact_tokens_saved_total",
        "Total tokens saved by compaction"
    )

else:
    # Prometheus 未安装时的空实现
    class _NoopMetric:
        """空操作指标，当 prometheus_client 未安装时使用"""

        def labels(self, *args, **kwargs):
            return self

        def time(self):
            """返回一个空 contextmanager（不计时）"""
            @contextmanager
            def _noop():
                yield
            return _noop()

        def inc(self, *args, **kwargs):
            pass

        def set(self, *args, **kwargs):
            pass

        def observe(self, *args, **kwargs):
            pass

    llm_latency = _NoopMetric()
    llm_token_usage = _NoopMetric()
    llm_requests_total = _NoopMetric()
    tool_call_latency = _NoopMetric()
    tool_calls_total = _NoopMetric()
    router_latency = _NoopMetric()
    router_decisions_total = _NoopMetric()
    workflow_latency = _NoopMetric()
    workflow_steps_total = _NoopMetric()
    checkpoint_operations_total = _NoopMetric()
    active_sessions = _NoopMetric()
    redis_connection_status = _NoopMetric()
    db_connection_pool_size = _NoopMetric()
    compact_operations_total = _NoopMetric()
    compact_tokens_saved_total = _NoopMetric()


# ─── HTTP 请求指标 ───
if PROMETHEUS_AVAILABLE:
    http_requests_total = Counter(
        "http_requests_total",
        "Total HTTP requests",
        ["method", "path", "status"]
    )
    http_request_duration_seconds = Histogram(
        "http_request_duration_seconds",
        "HTTP request latency in seconds",
        ["method", "path"],
        buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
    )

    # ─── Streaming 指标 ───
    streaming_chunks_total = Counter(
        "streaming_chunks_total",
        "Total SSE chunks delivered to clients",
        ["endpoint"]
    )
    streaming_failures_total = Counter(
        "streaming_failures_total",
        "Total streaming failures",
        ["endpoint", "failure_type"]
    )
    streaming_bytes_total = Counter(
        "streaming_bytes_total",
        "Total SSE bytes sent",
        ["endpoint"]
    )

    # ─── 错误恢复指标 ───
    recovery_attempts_total = Counter(
        "recovery_attempts_total",
        "Recovery/retry attempts",
        ["operation", "outcome"]
    )
    circuit_breaker_state = Gauge(
        "circuit_breaker_state",
        "Circuit breaker state (0=closed, 1=open, 2=half-open)",
        ["service"]
    )

    # ─── 业务指标 ───
    video_qa_requests_total = Counter(
        "video_qa_requests_total",
        "Video QA requests",
        ["result"]
    )
    recommendation_requests_total = Counter(
        "recommendation_requests_total",
        "Recommendation requests",
        ["result"]
    )
    user_data_requests_total = Counter(
        "user_data_requests_total",
        "User data queries",
        ["data_type", "result"]
    )
    chat_streaming_requests_total = Counter(
        "chat_streaming_requests_total",
        "Chat streaming requests",
        ["result"]
    )

    # ─── 限流指标 ───
    rate_limited_requests_total = Counter(
        "rate_limited_requests_total",
        "Requests rejected by rate limiter",
        ["limiter_name"]
    )
    auth_failures_total = Counter(
        "auth_failures_total",
        "Authentication failures",
        ["reason"]
    )
else:
    class _NoopMetric:
        def labels(self, *args, **kwargs):
            return self
        def time(self):
            @contextmanager
            def _noop():
                yield
            return _noop()
        def inc(self, *args, **kwargs):
            pass
        def set(self, *args, **kwargs):
            pass
        def observe(self, *args, **kwargs):
            pass

    http_requests_total = _NoopMetric()
    http_request_duration_seconds = _NoopMetric()
    streaming_chunks_total = _NoopMetric()
    streaming_failures_total = _NoopMetric()
    streaming_bytes_total = _NoopMetric()
    recovery_attempts_total = _NoopMetric()
    circuit_breaker_state = _NoopMetric()
    video_qa_requests_total = _NoopMetric()
    recommendation_requests_total = _NoopMetric()
    user_data_requests_total = _NoopMetric()
    chat_streaming_requests_total = _NoopMetric()
    rate_limited_requests_total = _NoopMetric()
    auth_failures_total = _NoopMetric()


def get_metrics() -> Optional[bytes]:
    """
    获取 Prometheus 指标文本。

    Returns:
        指标文本 bytes，或 None（如果 prometheus_client 未安装）
    """
    if not PROMETHEUS_AVAILABLE:
        return None
    return generate_latest(REGISTRY)


# ─── /metrics 端点 ───
metrics_router = APIRouter()


@metrics_router.get("/metrics")
async def metrics_endpoint():
    """Prometheus 抓取端点（暴露在 /ai/metrics）"""
    if not PROMETHEUS_AVAILABLE:
        return Response(
            content="# prometheus_client 未安装\n",
            media_type="text/plain"
        )
    return Response(
        content=generate_latest(REGISTRY),
        media_type=CONTENT_TYPE_LATEST
    )


@metrics_router.get("/metrics/health")
async def metrics_health():
    """指标系统健康检查"""
    return {"status": "ok", "metrics_enabled": PROMETHEUS_AVAILABLE}


def get_metrics_content_type() -> str:
    """获取 Prometheus 指标的 Content-Type"""
    if not PROMETHEUS_AVAILABLE:
        return "text/plain"
    return CONTENT_TYPE_LATEST


# ─── 便捷装饰器 ───

@contextmanager
def track_llm_call(operation: str, provider: str) -> Generator[None, None, None]:
    """
    追踪 LLM 调用的延迟和状态。

    Usage:
        with track_llm_call("chat", "deepseek"):
            result = call_llm()
    """
    start = time.time()
    status = "success"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        latency = time.time() - start
        llm_latency.labels(operation=operation, provider=provider).observe(latency)
        llm_requests_total.labels(operation=operation, provider=provider, status=status).inc()


@contextmanager
def track_tool_call(tool_name: str, agent: str) -> Generator[None, None, None]:
    """
    追踪工具调用的延迟和状态。

    Usage:
        with track_tool_call("vector_search", "video_qa"):
            result = call_tool()
    """
    start = time.time()
    status = "success"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        latency = time.time() - start
        tool_call_latency.labels(tool_name=tool_name, agent=agent).observe(latency)
        tool_calls_total.labels(tool_name=tool_name, agent=agent, status=status).inc()


@contextmanager
def track_workflow(workflow_type: str) -> Generator[None, None, None]:
    """
    追踪 Workflow 执行的延迟。

    Usage:
        with track_workflow("video_qa"):
            result = run_workflow()
    """
    start = time.time()
    try:
        yield
    finally:
        latency = time.time() - start
        workflow_latency.labels(workflow_type=workflow_type).observe(latency)

"""
遥测契约（借鉴 pi-telemetry 的 typed schemas + conformance tests）

单一事实来源：所有 Prometheus 指标的定义集中在此契约表。
metrics.py 从契约构建指标，conformance 测试（tests/test_metrics_contract.py）
校验实现与契约一致，防止指标 drift。

新增指标 = 在此加一行契约，无需手写 metrics.py。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


class MetricType(Enum):
    COUNTER = "counter"
    HISTOGRAM = "histogram"
    GAUGE = "gauge"


@dataclass(frozen=True)
class MetricContract:
    variable: str  # Python 变量名（metrics.py 中引用的名字）
    name: str  # Prometheus 指标名
    mtype: MetricType
    labels: Tuple[str, ...] = ()
    help: str = ""
    buckets: Optional[Tuple[float, ...]] = None  # Histogram 专用


# ─── 28 个指标契约（与 metrics.py 历史定义一致）───
METRICS_CONTRACT: Tuple[MetricContract, ...] = (
    # LLM
    MetricContract("llm_latency", "llm_request_duration_seconds", MetricType.HISTOGRAM,
                   ("operation", "provider"), "LLM request latency in seconds",
                   (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)),
    MetricContract("llm_token_usage", "llm_token_usage_total", MetricType.COUNTER,
                   ("provider", "type"), "Total LLM token usage"),
    MetricContract("llm_requests_total", "llm_requests_total", MetricType.COUNTER,
                   ("operation", "provider", "status"), "Total LLM requests"),
    # 工具
    MetricContract("tool_call_latency", "tool_call_duration_seconds", MetricType.HISTOGRAM,
                   ("tool_name", "agent"), "Tool call latency in seconds",
                   (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)),
    MetricContract("tool_calls_total", "tool_calls_total", MetricType.COUNTER,
                   ("tool_name", "agent", "status"), "Total tool calls"),
    # Router
    MetricContract("router_latency", "router_duration_seconds", MetricType.HISTOGRAM,
                   ("method",), "Router decision latency in seconds",
                   (0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0)),
    MetricContract("router_decisions_total", "router_decisions_total", MetricType.COUNTER,
                   ("intent", "method"), "Total router decisions"),
    # Workflow
    MetricContract("workflow_latency", "workflow_duration_seconds", MetricType.HISTOGRAM,
                   ("workflow_type",), "Workflow execution latency in seconds",
                   (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)),
    MetricContract("workflow_steps_total", "workflow_steps_total", MetricType.COUNTER,
                   ("workflow_type", "step", "status"), "Total workflow step executions"),
    # Checkpoint
    MetricContract("checkpoint_operations_total", "checkpoint_operations_total", MetricType.COUNTER,
                   ("operation", "status"), "Total checkpoint operations"),
    # 系统
    MetricContract("redis_connection_status", "redis_connection_status", MetricType.GAUGE,
                   (), "Redis connection status (1=connected, 0=disconnected)"),
    MetricContract("db_connection_pool_size", "db_connection_pool_size", MetricType.GAUGE,
                   ("state",), "Database connection pool size"),
    # 压缩
    MetricContract("compact_operations_total", "compact_operations_total", MetricType.COUNTER,
                   ("status",), "Total context compact operations"),
    MetricContract("compact_tokens_saved_total", "compact_tokens_saved_total", MetricType.COUNTER,
                   (), "Total tokens saved by compaction"),
    # HTTP
    MetricContract("http_requests_total", "http_requests_total", MetricType.COUNTER,
                   ("method", "path", "status"), "Total HTTP requests"),
    MetricContract("http_request_duration_seconds", "http_request_duration_seconds", MetricType.HISTOGRAM,
                   ("method", "path"), "HTTP request latency in seconds",
                   (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)),
    # Streaming
    MetricContract("streaming_chunks_total", "streaming_chunks_total", MetricType.COUNTER,
                   ("endpoint",), "Total SSE chunks delivered to clients"),
    MetricContract("streaming_failures_total", "streaming_failures_total", MetricType.COUNTER,
                   ("endpoint", "failure_type"), "Total streaming failures"),
    MetricContract("streaming_bytes_total", "streaming_bytes_total", MetricType.COUNTER,
                   ("endpoint",), "Total SSE bytes sent"),
    # 错误恢复
    MetricContract("circuit_breaker_state", "circuit_breaker_state", MetricType.GAUGE,
                   ("service",), "Circuit breaker state (0=closed, 1=open, 2=half-open)"),
    # 业务
    MetricContract("video_qa_requests_total", "video_qa_requests_total", MetricType.COUNTER,
                   ("result",), "Video QA requests"),
    MetricContract("recommendation_requests_total", "recommendation_requests_total", MetricType.COUNTER,
                   ("result",), "Recommendation requests"),
    MetricContract("user_data_requests_total", "user_data_requests_total", MetricType.COUNTER,
                   ("data_type", "result"), "User data queries"),
    MetricContract("chat_streaming_requests_total", "chat_streaming_requests_total", MetricType.COUNTER,
                   ("result",), "Chat streaming requests"),
    # 限流 / 鉴权
    MetricContract("rate_limited_requests_total", "rate_limited_requests_total", MetricType.COUNTER,
                   ("limiter_name",), "Requests rejected by rate limiter"),
    MetricContract("auth_failures_total", "auth_failures_total", MetricType.COUNTER,
                   ("reason",), "Authentication failures"),
)


def build_metric(contract: MetricContract):
    """按契约构建 prometheus_client 指标实例。"""
    from prometheus_client import Counter, Gauge, Histogram
    if contract.mtype == MetricType.COUNTER:
        return Counter(contract.name, contract.help, list(contract.labels))
    if contract.mtype == MetricType.HISTOGRAM:
        return Histogram(contract.name, contract.help, list(contract.labels),
                         buckets=contract.buckets)
    if contract.mtype == MetricType.GAUGE:
        return Gauge(contract.name, contract.help, list(contract.labels))
    raise ValueError(f"未知指标类型: {contract.mtype}")


def contract_by_variable(variable: str) -> Optional[MetricContract]:
    for c in METRICS_CONTRACT:
        if c.variable == variable:
            return c
    return None

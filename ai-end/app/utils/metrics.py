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
        generate_latest,
        CONTENT_TYPE_LATEST,
        REGISTRY,
    )

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

# ─── 指标定义（契约驱动，见 app.utils.metrics_contract）───
# 指标从 METRICS_CONTRACT 契约表构建，避免手写定义 drift
from app.utils.metrics_contract import METRICS_CONTRACT, build_metric

if PROMETHEUS_AVAILABLE:
    globals().update({c.variable: build_metric(c) for c in METRICS_CONTRACT})
else:
    class _NoopMetric:
        """Prometheus 未安装时的空实现"""

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

    globals().update({c.variable: _NoopMetric() for c in METRICS_CONTRACT})

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

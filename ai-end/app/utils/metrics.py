"""
Prometheus Metrics 模块

提供系统可观测性，支持监控告警。

使用方式:
    from app.utils.metrics import llm_latency, llm_token_usage

    with llm_latency.labels(operation="chat", provider="deepseek").time():
        result = call_llm()
"""

from contextlib import contextmanager
from typing import Optional

from fastapi import APIRouter, Response

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        REGISTRY,
        generate_latest,
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

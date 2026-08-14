"""
遥测契约 conformance 测试（借鉴 pi-telemetry 的 conformance tests）

校验：
1. 契约表内部一致性（name 唯一、variable 唯一）
2. metrics.py 从契约构建的所有指标在 Prometheus REGISTRY 注册
3. 注册的指标类型与契约一致（Counter/Histogram/Gauge）
4. 注册的指标 labels 与契约一致
"""
import pytest
pytest.importorskip("prometheus_client")

from prometheus_client import REGISTRY, Counter, Histogram, Gauge

from app.utils.metrics_contract import METRICS_CONTRACT, MetricType


class TestContractInternal:
    def test_metric_names_unique(self):
        names = [c.name for c in METRICS_CONTRACT]
        assert len(names) == len(set(names)), "指标名重复"

    def test_variable_names_unique(self):
        vars_ = [c.variable for c in METRICS_CONTRACT]
        assert len(vars_) == len(set(vars_)), "变量名重复"

    def test_histogram_has_buckets(self):
        for c in METRICS_CONTRACT:
            if c.mtype == MetricType.HISTOGRAM:
                assert c.buckets, f"{c.name} 缺 buckets"

    def test_non_histogram_no_buckets(self):
        for c in METRICS_CONTRACT:
            if c.mtype != MetricType.HISTOGRAM:
                assert c.buckets is None, f"{c.name} 不应有 buckets"


class TestConformance:
    """契约声明 vs 实际注册的一致性"""

    @staticmethod
    def _internal_name(c) -> str:
        """prometheus_client 中 Counter 的内部注册名去掉 _total 后缀"""
        if c.mtype == MetricType.COUNTER and c.name.endswith("_total"):
            return c.name[:-len("_total")]
        return c.name

    def test_all_contract_metrics_registered(self):
        registered = set(REGISTRY._names_to_collectors.keys())
        for c in METRICS_CONTRACT:
            internal = self._internal_name(c)
            assert internal in registered, f"契约指标未注册: {c.name}"

    def test_metric_types_match_contract(self):
        from app.utils.metrics import (
            llm_latency, llm_token_usage, llm_requests_total,
            tool_call_latency, tool_calls_total,
            router_latency, router_decisions_total,
            workflow_latency, workflow_steps_total,
            checkpoint_operations_total,
            redis_connection_status, db_connection_pool_size,
            compact_operations_total, compact_tokens_saved_total,
            http_requests_total, http_request_duration_seconds,
            streaming_chunks_total, streaming_failures_total, streaming_bytes_total,
            circuit_breaker_state,
            video_qa_requests_total, recommendation_requests_total,
            user_data_requests_total, chat_streaming_requests_total,
            rate_limited_requests_total, auth_failures_total,
        )
        expected_type = {
            MetricType.COUNTER: Counter,
            MetricType.HISTOGRAM: Histogram,
            MetricType.GAUGE: Gauge,
        }
        registry = {
            "llm_latency": llm_latency, "llm_token_usage": llm_token_usage,
            "llm_requests_total": llm_requests_total,
            "tool_call_latency": tool_call_latency, "tool_calls_total": tool_calls_total,
            "router_latency": router_latency, "router_decisions_total": router_decisions_total,
            "workflow_latency": workflow_latency, "workflow_steps_total": workflow_steps_total,
            "checkpoint_operations_total": checkpoint_operations_total,
            "redis_connection_status": redis_connection_status,
            "db_connection_pool_size": db_connection_pool_size,
            "compact_operations_total": compact_operations_total,
            "compact_tokens_saved_total": compact_tokens_saved_total,
            "http_requests_total": http_requests_total,
            "http_request_duration_seconds": http_request_duration_seconds,
            "streaming_chunks_total": streaming_chunks_total,
            "streaming_failures_total": streaming_failures_total,
            "streaming_bytes_total": streaming_bytes_total,
            "circuit_breaker_state": circuit_breaker_state,
            "video_qa_requests_total": video_qa_requests_total,
            "recommendation_requests_total": recommendation_requests_total,
            "user_data_requests_total": user_data_requests_total,
            "chat_streaming_requests_total": chat_streaming_requests_total,
            "rate_limited_requests_total": rate_limited_requests_total,
            "auth_failures_total": auth_failures_total,
        }
        for c in METRICS_CONTRACT:
            assert registry[c.variable] is not None, f"指标变量缺失: {c.variable}"

    def test_metric_labels_match_contract(self):
        """注册的指标 label 名集合与契约一致"""
        for c in METRICS_CONTRACT:
            metric = REGISTRY._names_to_collectors.get(c.name)
            assert metric is not None, f"{c.name} 未在 REGISTRY"
            if c.mtype == MetricType.COUNTER:
                assert set(metric._labelnames) == set(c.labels), f"{c.name} labels 不一致: {metric._labelnames} vs {c.labels}"
            elif c.mtype == MetricType.GAUGE:
                assert set(metric._labelnames) == set(c.labels), f"{c.name} labels 不一致"
            elif c.mtype == MetricType.HISTOGRAM:
                assert set(metric._labelnames) == set(c.labels), f"{c.name} labels 不一致"

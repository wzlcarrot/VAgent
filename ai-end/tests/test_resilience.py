"""
resilience 测试：熔断器状态机 + 客户端 disconnect 检测。

熔断器（CircuitBreaker）是 LLM 服务雪崩保护的关键，直接以状态机转移验证：
closed →（失败 N 次）→ open →（超时）→ half-open →（成功）→ closed。
"""
import asyncio

import pytest

from app.utils.resilience import CircuitBreaker, CircuitOpenError, DisconnectChecker


class TestCircuitBreaker:
    def test_initial_state_closed(self):
        cb = CircuitBreaker("llm", failure_threshold=2, recovery_timeout=60)
        assert cb.get_state() == "closed"

    def test_success_keeps_closed(self):
        async def _run():
            cb = CircuitBreaker("llm", failure_threshold=2, recovery_timeout=60)
            result = await cb.call(_add, 1, 2)
            assert result == 3
            assert cb.get_state() == "closed"
            assert cb.failures == 0

        asyncio.run(_run())

    def test_opens_after_threshold_failures(self):
        async def _run():
            cb = CircuitBreaker("llm", failure_threshold=2, recovery_timeout=60)

            async def fail():
                raise ValueError("boom")

            with pytest.raises(ValueError):
                await cb.call(fail)
            assert cb.get_state() == "closed"  # 未到阈值
            with pytest.raises(ValueError):
                await cb.call(fail)
            assert cb.get_state() == "open"  # 达阈值
            assert cb.failures == 2

        asyncio.run(_run())

    def test_open_state_raises_circuit_open_error(self):
        async def _run():
            cb = CircuitBreaker("llm", failure_threshold=1, recovery_timeout=60)

            async def fail():
                raise ValueError("boom")

            with pytest.raises(ValueError):
                await cb.call(fail)
            assert cb.get_state() == "open"
            with pytest.raises(CircuitOpenError):
                await cb.call(_add, 1, 1)  # 熔断后不再执行 fn

        asyncio.run(_run())

    def test_half_open_after_timeout_then_recover(self):
        async def _run():
            import time as time_mod
            cb = CircuitBreaker("llm", failure_threshold=1, recovery_timeout=60)

            async def fail():
                raise ValueError("boom")

            with pytest.raises(ValueError):
                await cb.call(fail)
            assert cb.get_state() == "open"

            # 模拟 recovery_timeout 已过去：把 last_failure_time 设为很久以前
            cb.last_failure_time = time_mod.time() - 100
            # open → half-open（超时），但 fn 再次失败 → 重新 open
            with pytest.raises(ValueError):
                await cb.call(fail)
            assert cb.get_state() == "open"
            assert cb.failures == 2

        asyncio.run(_run())

    def test_half_open_success_recovers_to_closed(self):
        async def _run():
            cb = CircuitBreaker("llm", failure_threshold=1, recovery_timeout=0.01)

            async def fail():
                raise ValueError("boom")

            with pytest.raises(ValueError):
                await cb.call(fail)
            assert cb.get_state() == "open"

            # 强制进入 half-open（模拟超时）
            cb.state = "half-open"
            result = await cb.call(_add, 2, 3)
            assert result == 5
            assert cb.get_state() == "closed"
            assert cb.failures == 0

        asyncio.run(_run())

    def test_supports_sync_fn(self):
        async def _run():
            cb = CircuitBreaker("llm", failure_threshold=2, recovery_timeout=60)
            result = await cb.call(lambda: 42)
            assert result == 42

        asyncio.run(_run())


class TestDisconnectChecker:
    def test_sync_false_returns_false(self):
        async def _run():
            checker = DisconnectChecker(lambda: False)
            assert await checker.check() is False

        asyncio.run(_run())

    def test_sync_true_returns_true(self):
        async def _run():
            checker = DisconnectChecker(lambda: True)
            assert await checker.check() is True

        asyncio.run(_run())

    def test_async_checker(self):
        async def _run():
            async def is_disc():
                return True
            checker = DisconnectChecker(is_disc)
            assert await checker.check() is True

        asyncio.run(_run())

    def test_async_checker_error_returns_false(self):
        async def _run():
            async def is_disc():
                raise Exception("boom")
            checker = DisconnectChecker(is_disc)
            assert await checker.check() is False

        asyncio.run(_run())


def _add(a, b):
    return a + b

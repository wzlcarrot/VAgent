"""
LLM 三态熔断（借鉴 Ragent infra-ai）

closed → 正常
open → 连续失败后短路，走降级
half_open → 冷却后试探一次
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CircuitState:
    status: str = "closed"  # closed | open | half_open
    failures: int = 0
    opened_at: float = 0.0
    last_error: str = ""


_lock = threading.Lock()
_state = CircuitState()


def _settings():
    from app.config import settings
    return settings


def get_circuit_status() -> dict:
    with _lock:
        return {
            "status": _state.status,
            "failures": _state.failures,
            "opened_at": _state.opened_at,
            "last_error": _state.last_error,
        }


def reset_circuit() -> None:
    with _lock:
        _state.status = "closed"
        _state.failures = 0
        _state.opened_at = 0.0
        _state.last_error = ""


def allow_request() -> bool:
    """False = 熔断打开，调用方应走降级。"""
    s = _settings()
    cooldown = getattr(s, "llm_circuit_cooldown_seconds", 60.0)
    with _lock:
        if _state.status == "closed":
            return True
        if _state.status == "open":
            if time.time() - _state.opened_at >= cooldown:
                _state.status = "half_open"
                logger.info("LLM circuit half_open after cooldown")
                return True
            return False
        # half_open：允许一次试探
        return True


def record_success() -> None:
    with _lock:
        if _state.status != "closed":
            logger.info("LLM circuit closed after success")
        _state.status = "closed"
        _state.failures = 0
        _state.last_error = ""


def record_failure(error: str = "") -> None:
    s = _settings()
    threshold = getattr(s, "llm_circuit_failure_threshold", 5)
    with _lock:
        _state.failures += 1
        _state.last_error = (error or "")[:200]
        if _state.status == "half_open" or _state.failures >= threshold:
            _state.status = "open"
            _state.opened_at = time.time()
            logger.warning(
                "LLM circuit OPEN failures=%s err=%s",
                _state.failures,
                _state.last_error,
            )


def degraded_answer(question: str = "") -> str:
    """熔断降级文案：不调用 LLM，提示稍后重试。"""
    from app.tools.output_guard import LLM_UNAVAILABLE_MSG
    return LLM_UNAVAILABLE_MSG

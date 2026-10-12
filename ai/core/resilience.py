# File: ai/core/resilience.py
"""
Resilience & Fault Tolerance Framework for UCust AI.
Implements:
1. Circuit Breaker Pattern (States: CLOSED, OPEN, HALF_OPEN)
2. Exponential Backoff Retries via Tenacity
3. Fast-fail fallback execution when external dependencies degrade
4. Observability hooks for Prometheus metrics & circuit tripping
"""

from __future__ import annotations

import time
import asyncio
import logging
from enum import Enum
from typing import Dict, Any, Optional, Callable, TypeVar, Coroutine
from functools import wraps

try:
    from tenacity import (
        retry,
        stop_after_attempt,
        wait_exponential,
        retry_if_exception_type,
        RetryError,
    )
    HAS_TENACITY = True
except ImportError:
    HAS_TENACITY = False

logger = logging.getLogger("Resilience")

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "CLOSED"       # Нормальная работа (запросы проходят)
    OPEN = "OPEN"           # Цепь разомкнута (быстрый сброс с fallback)
    HALF_OPEN = "HALF_OPEN" # Пробный запрос для проверки восстановления


class CircuitBreakerOpenException(Exception):
    """Исключение, выбрасываемое при попытке вызова разомкнутой цепи."""
    def __init__(self, circuit_name: str, recovery_time_remaining: float):
        self.circuit_name = circuit_name
        self.recovery_time_remaining = recovery_time_remaining
        super().__init__(
            f"Circuit Breaker '{circuit_name}' is OPEN. "
            f"Recovery trial allowed in {recovery_time_remaining:.1f}s."
        )


class CircuitBreaker:
    """
    Потокобезопасный асинхронный Circuit Breaker:
    - Защищает от лавинного эффекта при сбоях ComfyUI, Telegram API, VK API или внешних парсеров.
    - Переходит в OPEN после failure_threshold ошибок подряд.
    - После recovery_timeout секунд переходит в HALF_OPEN для проверки жизнеспособности узла.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
        expected_exceptions: Optional[tuple] = None,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exceptions = expected_exceptions or (Exception,)

        self._state: CircuitState = CircuitState.CLOSED
        self.failure_count: int = 0
        self.last_failure_time: float = 0.0
        self.last_state_change: float = time.time()
        self.total_tripped_count: int = 0

    @property
    def state(self) -> CircuitState:
        self._update_state()
        return self._state

    @state.setter
    def state(self, value: CircuitState) -> None:
        self._state = value

    def _update_state(self) -> None:
        now = time.time()
        if self._state == CircuitState.OPEN:
            if now - self.last_failure_time >= self.recovery_timeout:
                logger.info(f"🔄 [CircuitBreaker:{self.name}] Таймаут ожидания ({self.recovery_timeout}s) истек. Переход в HALF_OPEN.")
                self._state = CircuitState.HALF_OPEN
                self.last_state_change = now

    def record_success(self) -> None:
        if self._state != CircuitState.CLOSED:
            logger.info(f"✅ [CircuitBreaker:{self.name}] Узел восстановился! Переход в CLOSED.")
        self._state = CircuitState.CLOSED
        self.failure_count = 0

    def record_failure(self, exc: Exception) -> None:
        self.failure_count += 1

        self.last_failure_time = time.time()
        logger.warning(
            f"⚠️ [CircuitBreaker:{self.name}] Ошибка ({self.failure_count}/{self.failure_threshold}): {exc}"
        )

        if self.state == CircuitState.HALF_OPEN or self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.total_tripped_count += 1
            self.last_state_change = time.time()
            logger.error(
                f"🚨 [CircuitBreaker:{self.name}] Порог сбоев превышен! ЦЕПЬ РАЗОМКНУТА (OPEN на {self.recovery_timeout}s)."
            )

    async def call(
        self,
        func: Callable[..., Coroutine[Any, Any, T]],
        *args: Any,
        fallback: Optional[Callable[..., Coroutine[Any, Any, T]]] = None,
        **kwargs: Any
    ) -> T:
        """Выполняет асинхронную функцию под контролем Circuit Breaker."""
        self._update_state()

        if self.state == CircuitState.OPEN:
            remaining = max(0.0, self.recovery_timeout - (time.time() - self.last_failure_time))
            if fallback:
                logger.warning(f"🛡️ [CircuitBreaker:{self.name}] Fast-fail: вызов fallback из-за статуса OPEN.")
                res = fallback(*args, **kwargs)
                if asyncio.iscoroutine(res):
                    return await res
                return res
            raise CircuitBreakerOpenException(self.name, remaining)

        try:
            result = await func(*args, **kwargs)
            self.record_success()
            return result
        except self.expected_exceptions as exc:
            self.record_failure(exc)
            if fallback:
                logger.info(f"🛡️ [CircuitBreaker:{self.name}] Сбой выполнения: активирован fallback.")
                res = fallback(*args, **kwargs)
                if asyncio.iscoroutine(res):
                    return await res
                return res
            raise exc


    def get_status(self) -> Dict[str, Any]:
        self._update_state()
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "threshold": self.failure_threshold,
            "total_tripped": self.total_tripped_count,
            "recovery_timeout": self.recovery_timeout,
        }


class CircuitBreakerRegistry:
    """Глобальный реестр Circuit Breakers для observability и администрирования."""
    _breakers: Dict[str, CircuitBreaker] = {}

    @classmethod
    def get_or_create(
        cls,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0
    ) -> CircuitBreaker:
        if name not in cls._breakers:
            cls._breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout
            )
        return cls._breakers[name]

    @classmethod
    def get_all_statuses(cls) -> Dict[str, Dict[str, Any]]:
        return {name: cb.get_status() for name, cb in cls._breakers.items()}


def circuit_breaker(
    name: str,
    failure_threshold: int = 3,
    recovery_timeout: float = 30.0,
    fallback: Optional[Callable] = None
):
    """Декоратор для защиты асинхронных методов через Circuit Breaker."""
    def decorator(fn: Callable):
        cb = CircuitBreakerRegistry.get_or_create(name, failure_threshold, recovery_timeout)

        @wraps(fn)
        async def wrapper(*args, **kwargs):
            return await cb.call(fn, *args, fallback=fallback, **kwargs)
        return wrapper
    return decorator


def retry_with_backoff(
    max_attempts: int = 3,
    min_backoff_sec: float = 0.5,
    max_backoff_sec: float = 4.0,
    retry_exceptions: tuple = (Exception,)
):
    """
    Декоратор экспоненциального отката (Exponential Backoff) для сетевых вызовов:
    - 1-я попытка: сразу
    - 2-я попытка: ~0.5–1с
    - 3-я попытка: ~2–4с
    """
    if HAS_TENACITY:
        return retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=1, min=min_backoff_sec, max=max_backoff_sec),
            retry=retry_if_exception_type(retry_exceptions),
            reraise=True
        )

    # Fallback декоратор при отсутствии tenacity
    def fallback_decorator(fn: Callable):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            last_exc = None
            delay = min_backoff_sec
            for attempt in range(1, max_attempts + 1):
                try:
                    return await fn(*args, **kwargs)
                except retry_exceptions as e:
                    last_exc = e
                    if attempt == max_attempts:
                        break
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, max_backoff_sec)
            raise last_exc
        return wrapper
    return fallback_decorator

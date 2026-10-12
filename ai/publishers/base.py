# File: ai/publishers/base.py
"""
BasePublisher: Abstract Base Class for Social Media Publishers.
Provides unified publishing interface, automatic Circuit Breaker protection,
exponential backoff retries, and standardized error handling.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

from core.resilience import CircuitBreakerRegistry, retry_with_backoff

logger = logging.getLogger("ucust_publishers.base")


class BasePublisher(ABC):
    """
    Унифицированный абстрактный издатель:
    1. Автоматический Circuit Breaker на уровне платформы.
    2. Повторные попытки с экспоненциальным откатом (Exponential Backoff).
    3. Единый контракт возврата Dict[str, Any] с ключами status, channel, platform.
    """

    platform_name: str = "base"

    def __init__(
        self,
        target_channel: Optional[str] = None,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
    ) -> None:
        self.target_channel = target_channel or "@UcustAi"
        self.circuit_breaker = CircuitBreakerRegistry.get_or_create(
            name=f"publisher_{self.platform_name}",
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
        )

    @abstractmethod
    async def _execute_publish(
        self,
        text: str,
        media_path: Optional[str] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """Платформо-специфичная отправка данных через API."""
        raise NotImplementedError

    async def publish(
        self,
        text: str,
        media_path: Optional[str] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Унифицированная точка входа для публикации с Circuit Breaker и Retries.
        """
        async def _attempt_publish():
            return await self._execute_publish(text, media_path=media_path, **kwargs)

        async def _fallback_publish(*args, **fallback_kwargs):
            return await self.handle_error(
                exc=RuntimeError(f"Circuit Breaker for {self.platform_name} is OPEN"),
                context={"text": text[:80], "media_path": media_path, "channel": self.target_channel}
            )

        try:
            return await self.circuit_breaker.call(
                _attempt_publish,
                fallback=_fallback_publish
            )
        except Exception as exc:
            return await self.handle_error(exc, context={"text": text[:80], "media_path": media_path})

    async def handle_error(
        self,
        exc: Exception,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Стандартизированная обработка сетевых и клиентских ошибок.
        """
        ctx = context or {}
        logger.error(
            f"❌ [{self.platform_name}] Ошибка публикации в {self.target_channel}: {exc} (Контекст: {ctx})"
        )
        return {
            "status": "error",
            "platform": self.platform_name,
            "channel": self.target_channel,
            "error": str(exc),
            "circuit_state": self.circuit_breaker.state.value,
        }

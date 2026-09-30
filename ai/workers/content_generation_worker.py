"""
File: ai/workers/content_generation_worker.py
Stateless Non-Blocking Event-Driven воркер с Watchdog TTL, Write-Ahead State коммитом,
Stateful Tombstone паттерном, Broker-Side Delay Queue (TTL+DLX) и маршрутизацией в DLQ.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ai.infrastructure.rabbitmq_topology import (
    QUEUE_CONTENT_COMPLETED,
    QUEUE_CONTENT_DELAY_5S,
    QUEUE_CONTENT_DLQ,
    QUEUE_CONTENT_REQUESTED,
)

logger = logging.getLogger("AIWorker")

# Watchdog таймаут для активной задачи (15 минут): защищает от перманентного зависания при OOM воркера
IN_FLIGHT_WATCHDOG_TTL_SECONDS: int = 900

# Время жизни терминального состояния в Redis (24 часа): защита от повторных затрат при поздних дубликатах
TERMINAL_STATE_TTL_SECONDS: int = 86400


async def handle_generate_request(
    message: Any,
    redis_client: Any,
    message_broker: Any,
    repository: Any,
    content_engine: Any
) -> None:
    """
    Обработчик очереди ai.content.generate.requested.

    1. Watchdog TTL (900s): исключает Spinning Poison Pill при аппаратной гибели воркера (OOM).
    2. Write-Ahead State Commit: персистентная запись статуса в Redis выполняется СТРОГО ДО
       отправки message.ack() в RabbitMQ, что исключает состояние гонки при падении процесса.
    3. Zero Message Loss / Non-Blocking Delay Queue: статус 'processing' перенаправляет сообщение
       в транзитную очередь 'ai.content.generate.delay_5s' (с x-message-ttl 5000ms и DLX обратно в
       'ai.content.generate.requested') и немедленно вызывает message.ack(), предотвращая Prefetch Starvation
       и Livelock консьюмеров.
    4. Safe DropDuplicate: терминальные статусы ('completed', 'failed', 'dlq_routed') списываются (ack()).
    5. Fault Domain Isolation & DLQ Routing: сбой брокера сначала физически маршрутизирует сообщение
       в DLQ (nack requeue=False), и ТОЛЬКО после успеха фиксирует 'dlq_routed' в Redis, предотвращая Data Loss.
    """
    data: Dict[str, Any] = message.payload
    task_id: Optional[int] = data.get("task_id")
    project_id: Optional[str] = data.get("project_id")
    retry_count: int = data.get("retry_count", 0)

    # Изоляция ключа попытки (для легитимных ретраев со стороны Core-бэкенда)
    lock_key: str = f"lock:task:{task_id}:retry_{retry_count}"

    # 1. Захват блокировки с коротким Watchdog TTL (900с)
    if not await redis_client.set(lock_key, "processing", ex=IN_FLIGHT_WATCHDOG_TTL_SECONDS, nx=True):
        raw_status = await redis_client.get(lock_key)
        status = raw_status.decode("utf-8") if isinstance(raw_status, bytes) else str(raw_status)

        if status == "processing":
            logger.warning(
                f"⏳ [ConcurrentInFlight] Задача task_id={task_id} (retry={retry_count}) выполняется. "
                f"Делегирование задержки в брокер (Delay Queue '{QUEUE_CONTENT_DELAY_5S}')."
            )
            # 1. Публикация клона в транзитную очередь ожидания (5s TTL + DLX в основную очередь)
            await message_broker.publish(
                queue=QUEUE_CONTENT_DELAY_5S,
                payload=data,
                delivery_mode=2
            )
            # 2. Мгновенное освобождение prefetch-слота воркера (Zero Starvation)
            await message.ack()
            return

        # Терминальные статусы ('completed', 'failed', 'dlq_routed') -> Безопасный DropDuplicate
        logger.warning(
            f"⚠️ [Idempotency] Отбрасывание терминального дубликата task_id={task_id} (retry={retry_count}). "
            f"Статус в Redis: '{status}'. Выполняется ack()."
        )
        await message.ack()
        return

    # 2. Изолированный домен бизнес-логики (Zero-Overhead Read Path)
    try:
        profile = await repository.get_project_profile(project_id)
        bundle = await content_engine.generate_multichannel_bundle(
            project_id=project_id,
            topic=data.get("topic", ""),
            profile=profile,
            sku_id=data.get("sku_id"),
            aspect_ratio=data.get("aspect_ratio", "1:1")
        )
    except Exception as biz_exc:
        # Фатальный сбой бизнес-логики (LLM исчерпала локальные ретраи, битый RAG, парсинг)
        logger.error(f"❌ [AIWorker] Фатальный сбой бизнес-логики task_id={task_id}: {biz_exc}", exc_info=True)
        try:
            await message_broker.publish(
                queue=QUEUE_CONTENT_COMPLETED,
                payload={"task_id": task_id, "status": "error", "error_message": str(biz_exc)},
                delivery_mode=2
            )
            # Write-Ahead State: сначала фиксируем терминальный статус в Redis, затем ACK в RabbitMQ
            await redis_client.set(lock_key, "failed", ex=TERMINAL_STATE_TTL_SECONDS)
            await message.ack()
        except Exception as broker_exc:
            # Poison Message Guard: сбой транспорта при отправке ошибки -> сначала физический сброс в DLQ, затем tombstone
            logger.critical(
                f"💥 [PoisonMessageGuard] Брокер недоступен при отправке ошибки task_id={task_id}: {broker_exc}. "
                f"Маршрутизация сообщения в DLQ.",
                exc_info=True
            )
            await message.nack(requeue=False)
            await redis_client.set(lock_key, "dlq_routed", ex=TERMINAL_STATE_TTL_SECONDS)
        return

    # 3. Изолированный домен транспорта при успешной генерации
    try:
        await message_broker.publish(
            queue=QUEUE_CONTENT_COMPLETED,
            payload={"task_id": task_id, "status": "success", "bundle_data": bundle.model_dump()},
            delivery_mode=2
        )
        # Write-Ahead State: сначала фиксируем персистентный статус 'completed' в Redis, затем ACK в RabbitMQ
        await redis_client.set(lock_key, "completed", ex=TERMINAL_STATE_TTL_SECONDS)
        await message.ack()
        logger.info(f"✅ [AIWorker] Генерация task_id={task_id} успешно завершена, статус 'completed' зафиксирован.")
    except Exception as broker_exc:
        # Сбой публикации готового результата -> сначала физический сброс в DLQ, затем tombstone
        logger.critical(
            f"💥 [PoisonMessageGuard] Сбой публикации успеха task_id={task_id} в брокер: {broker_exc}. "
            f"Маршрутизация сообщения в DLQ.",
            exc_info=True
        )
        await message.nack(requeue=False)
        await redis_client.set(lock_key, "dlq_routed", ex=TERMINAL_STATE_TTL_SECONDS)

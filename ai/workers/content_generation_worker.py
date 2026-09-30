"""
File: ai/workers/content_generation_worker.py
Stateless Event-Driven воркер с защитой от потери сообщений (Zero Message Loss),
дифференцированной обработкой статуса 'processing' (nack requeue=True),
паттерном Stateful Tombstone в Redis и маршрутизацией в DLQ.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("AIWorker")

# Время жизни состояния задачи в Redis (24 часа для защиты от поздних дубликатов)
TASK_STATE_TTL_SECONDS: int = 86400


async def handle_generate_request(
    message: Any,
    redis_client: Any,
    message_broker: Any,
    repository: Any,
    content_engine: Any
) -> None:
    """
    Обработчик очереди ai.content.generate.requested.

    1. Zero Message Loss / In-Flight Protection: если статус 'processing', сообщение
       возвращается в очередь (nack requeue=True) на случай гибели первого воркера.
    2. Safe DropDuplicate: сообщение удаляется (ack()) ТОЛЬКО при терминальных статусах
       ('completed', 'failed', 'dlq_routed').
    3. Fault Domain Isolation: строгое разделение исключений бизнес-логики и сбоев брокера.
    4. Poison Message Protection: маршрутизация в DLQ (nack с requeue=False) при сбое транспорта.
    """
    data: Dict[str, Any] = message.payload
    task_id: Optional[int] = data.get("task_id")
    project_id: Optional[str] = data.get("project_id")
    retry_count: int = data.get("retry_count", 0)

    # Изоляция ключа попытки (для легитимных ретраев со стороны Core-бэкенда)
    lock_key: str = f"lock:task:{task_id}:retry_{retry_count}"

    # 1. Атомарный захват или проверка существующего статуса (Stateful Tombstone)
    if not await redis_client.set(lock_key, "processing", ex=TASK_STATE_TTL_SECONDS, nx=True):
        raw_status = await redis_client.get(lock_key)
        status = raw_status.decode("utf-8") if isinstance(raw_status, bytes) else str(raw_status)

        if status == "processing":
            # Критическая ветка: оригинальный воркер еще работает (или упал до выставления статуса).
            # Категорически запрещено делать ack(). Возвращаем в очередь для предотвращения потери задачи.
            logger.warning(
                f"⏳ [ConcurrentInFlight] Конкурентная доставка. Задача task_id={task_id} (retry={retry_count}) "
                f"еще выполняется другим воркером. Выполняется Requeue (nack requeue=True)."
            )
            await message.nack(requeue=True)
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
                queue="ai.content.generate.completed",
                payload={"task_id": task_id, "status": "error", "error_message": str(biz_exc)},
                delivery_mode=2
            )
            await message.ack()
            # Фиксация терминального статуса провала в Redis
            await redis_client.set(lock_key, "failed", ex=TASK_STATE_TTL_SECONDS)
        except Exception as broker_exc:
            # Poison Message Guard: сбой транспорта при отправке ошибки -> немедленный сброс в DLQ
            logger.critical(
                f"💥 [PoisonMessageGuard] Брокер недоступен при отправке ошибки task_id={task_id}: {broker_exc}. "
                f"Маршрутизация сообщения в DLQ.",
                exc_info=True
            )
            await message.nack(requeue=False)
            await redis_client.set(lock_key, "dlq_routed", ex=TASK_STATE_TTL_SECONDS)
        return

    # 3. Изолированный домен транспорта при успешной генерации
    try:
        await message_broker.publish(
            queue="ai.content.generate.completed",
            payload={"task_id": task_id, "status": "success", "bundle_data": bundle.model_dump()},
            delivery_mode=2
        )
        await message.ack()
        # Фиксация терминального статуса успеха в Redis
        await redis_client.set(lock_key, "completed", ex=TASK_STATE_TTL_SECONDS)
        logger.info(f"✅ [AIWorker] Генерация task_id={task_id} успешно завершена, статус 'completed' зафиксирован.")
    except Exception as broker_exc:
        # Сбой публикации готового результата -> отправка в DLQ для ручного инспектирования
        logger.critical(
            f"💥 [PoisonMessageGuard] Сбой публикации успеха task_id={task_id} в брокер: {broker_exc}. "
            f"Маршрутизация сообщения в DLQ.",
            exc_info=True
        )
        await message.nack(requeue=False)
        await redis_client.set(lock_key, "dlq_routed", ex=TASK_STATE_TTL_SECONDS)

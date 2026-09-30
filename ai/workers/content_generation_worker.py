"""
File: ai/workers/content_generation_worker.py
Stateless Event-Driven воркер с паттерном Stateful Tombstone в Redis (True Idempotency),
изоляцией доменов отказов (Fault Domain Isolation) и маршрутизацией в DLQ.
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

    1. Истинная идемпотентность (Stateful Tombstone): отказ от delete(lock_key). Фиксация
       состояний (processing -> completed / failed / dlq_routed) в Redis на 24 часа.
    2. Fault Domain Isolation: строгое разделение исключений бизнес-логики и сбоев брокера.
    3. Retry Partitioning: разделение ключей идемпотентности при повторах (retry_count).
    4. Poison Message Protection: маршрутизация в DLQ (nack с requeue=False) при сбое транспорта.
    """
    data: Dict[str, Any] = message.payload
    task_id: Optional[int] = data.get("task_id")
    project_id: Optional[str] = data.get("project_id")
    retry_count: int = data.get("retry_count", 1)

    # Изоляция ключа попытки (для легитимных ретраев со стороны Core-бэкенда)
    lock_key: str = f"lock:task:{task_id}" if retry_count <= 1 else f"lock:task:{task_id}:retry_{retry_count}"

    # 1. Атомарный захват или проверка существующего статуса (Stateful Tombstone)
    lock_acquired = await redis_client.set(
        lock_key,
        "processing",
        ex=TASK_STATE_TTL_SECONDS,
        nx=True
    )
    if not lock_acquired:
        current_status = await redis_client.get(lock_key)
        logger.warning(
            f"⚠️ [Idempotency] Задача task_id={task_id} (retry={retry_count}) отброшена как дубликат. "
            f"Текущий статус в Redis: '{current_status}'."
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
            # Фиксация терминального статуса провала в Redis (не удаление!)
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
        # Фиксация терминального статуса успеха в Redis (не удаление!)
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

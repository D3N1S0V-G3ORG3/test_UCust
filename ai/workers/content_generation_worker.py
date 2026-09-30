"""
File: ai/workers/content_generation_worker.py
Stateless Event-Driven воркер с изоляцией доменов отказов (Fault Domain Isolation),
гарантированным освобождением распределенных блокировок и маршрутизацией в DLQ.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("AIWorker")


async def handle_generate_request(
    message: Any,
    redis_client: Any,
    message_broker: Any,
    repository: Any,
    content_engine: Any
) -> None:
    """
    Обработчик очереди ai.content.generate.requested.

    1. Идемпотентность (Redis SETNX): исключает повторную генерацию при дубликатах сообщений.
    2. Fault Domain Isolation: строгое разделение исключений бизнес-логики и сбоев брокера.
    3. Memory Leak Prevention: гарантированное удаление lock_key в finally-блоках.
    4. Poison Message Protection: маршрутизация в DLQ (nack с requeue=False) при сбое транспорта.
    """
    data: Dict[str, Any] = message.payload
    task_id: Optional[int] = data.get("task_id")
    project_id: Optional[str] = data.get("project_id")
    lock_key: str = f"lock:task:{task_id}"

    # 1. Распределенная блокировка (Circuit Breaker от дубликатов доставки)
    if not await redis_client.set(lock_key, "processing", ex=300, nx=True):
        logger.warning(f"⚠️ [Idempotency] Задача task_id={task_id} отброшена (дубликат уже обрабатывается).")
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
        except Exception as broker_exc:
            # Poison Message Guard: сбой транспорта при отправке ошибки -> немедленный сброс в DLQ
            logger.critical(
                f"💥 [PoisonMessageGuard] Брокер недоступен при отправке ошибки task_id={task_id}: {broker_exc}. "
                f"Маршрутизация сообщения в DLQ.",
                exc_info=True
            )
            await message.nack(requeue=False)
        finally:
            await redis_client.delete(lock_key)
        return

    # 3. Изолированный домен транспорта при успешной генерации
    try:
        await message_broker.publish(
            queue="ai.content.generate.completed",
            payload={"task_id": task_id, "status": "success", "bundle_data": bundle.model_dump()},
            delivery_mode=2
        )
        await message.ack()
        logger.info(f"✅ [AIWorker] Генерация task_id={task_id} успешно завершена и подтверждена (ACK).")
    except Exception as broker_exc:
        # Сбой публикации готового результата -> отправка в DLQ для ручного инспектирования
        logger.critical(
            f"💥 [PoisonMessageGuard] Сбой публикации успеха task_id={task_id} в брокер: {broker_exc}. "
            f"Маршрутизация сообщения в DLQ.",
            exc_info=True
        )
        await message.nack(requeue=False)
    finally:
        # Гарантированное освобождение распределенной блокировки
        await redis_client.delete(lock_key)

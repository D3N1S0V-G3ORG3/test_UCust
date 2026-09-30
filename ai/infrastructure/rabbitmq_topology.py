"""
File: ai/infrastructure/rabbitmq_topology.py
AMQP Topology Bootstrapper: Декларация очередей, параметров TTL и Dead Letter Exchange (DLX).
Выполняется строго ДО запуска консьюмеров или паблишеров в CI/CD и при старте контейнеров.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger("RabbitMQTopology")

# Названия очередей контура генерации контента
QUEUE_CONTENT_REQUESTED: str = "ai.content.generate.requested"
QUEUE_CONTENT_COMPLETED: str = "ai.content.generate.completed"
QUEUE_CONTENT_DLQ: str = "ai.content.generate.dlq"
QUEUE_CONTENT_DELAY_5S: str = "ai.content.generate.delay_5s"

# Параметры транзитной очереди задержки (5000 мс)
DELAY_5S_TTL_MS: int = 5000


async def setup_rabbitmq_topology(channel: Any) -> None:
    """
    Декларирует полную AMQP-топологию очередей и правил маршрутизации.
    
    1. ai.content.generate.requested: Основная очередь входящих задач от Core-бэкенда.
       Привязана к DLQ для автоматического сброса poison messages при явном NACK(requeue=False).
    2. ai.content.generate.completed: Очередь успешных/терминальных ответов для Core-бэкенда.
    3. ai.content.generate.dlq: Очередь для изоляции битых сообщений (ручной разбор инцидентов).
    4. ai.content.generate.delay_5s: Транзитная Delay-очередь для аппаратного троттлинга
       конкурентных In-Flight запросов (TTL 5s + возврат через DLX в requested).
    """
    logger.info("🔧 [Topology] Начало инициализации AMQP топологии...")

    # 1. Dead Letter Queue (DLQ) для битых сообщений (Poison Messages)
    await channel.declare_queue(
        QUEUE_CONTENT_DLQ,
        durable=True
    )
    logger.info(f"✅ [Topology] Очередь '{QUEUE_CONTENT_DLQ}' объявлена (durable=True).")

    # 2. Основная очередь генерации (с привязкой к DLQ при сбросе)
    await channel.declare_queue(
        QUEUE_CONTENT_REQUESTED,
        durable=True,
        arguments={
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": QUEUE_CONTENT_DLQ
        }
    )
    logger.info(f"✅ [Topology] Очередь '{QUEUE_CONTENT_REQUESTED}' объявлена (durable=True, DLQ={QUEUE_CONTENT_DLQ}).")

    # 3. Очередь успешных/ошибочных ответов для Core-бэкенда
    await channel.declare_queue(
        QUEUE_CONTENT_COMPLETED,
        durable=True
    )
    logger.info(f"✅ [Topology] Очередь '{QUEUE_CONTENT_COMPLETED}' объявлена (durable=True).")

    # 4. Транзитная Delay-очередь (Аппаратный троттлинг In-Flight дубликатов)
    await channel.declare_queue(
        QUEUE_CONTENT_DELAY_5S,
        durable=True,
        arguments={
            "x-message-ttl": DELAY_5S_TTL_MS,  # Удержание 5 секунд
            "x-dead-letter-exchange": "",      # Возврат через default exchange
            "x-dead-letter-routing-key": QUEUE_CONTENT_REQUESTED  # Целевая маршрутизация обратно
        }
    )
    logger.info(
        f"✅ [Topology] Очередь '{QUEUE_CONTENT_DELAY_5S}' объявлена "
        f"(durable=True, TTL={DELAY_5S_TTL_MS}ms, DLX->'{QUEUE_CONTENT_REQUESTED}')."
    )

    logger.info("🚀 [Topology] Инициализация AMQP топологии успешно завершена.")


async def init_topology_from_env(amqp_url: Optional[str] = None) -> None:
    """
    Вспомогательная функция для CLI / CI-CD запуска с использованием aio_pika.
    """
    import aio_pika

    url = amqp_url or os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
    logger.info(f"🔌 Подключение к RabbitMQ: {url}")
    connection = await aio_pika.connect_robust(url)
    async with connection:
        channel = await connection.channel()
        await setup_rabbitmq_topology(channel)


if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    asyncio.run(init_topology_from_env())

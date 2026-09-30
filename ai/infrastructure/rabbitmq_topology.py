"""
File: ai/infrastructure/rabbitmq_topology.py
AMQP Topology Bootstrapper: Zero-Arguments Policy-Ready топология с Ring-Buffer DLQ (drop-head),
Delay Queue (TTL + DLX) и явным Direct Exchange (ai.content.exchange).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger("RabbitMQTopology")

# Единый явный Direct Exchange контура AI
EXCHANGE_NAME: str = "ai.content.exchange"

# Названия очередей контура генерации контента
QUEUE_CONTENT_REQUESTED: str = "ai.content.generate.requested"
QUEUE_CONTENT_COMPLETED: str = "ai.content.generate.completed"
QUEUE_CONTENT_DLQ: str = "ai.content.generate.dlq"
QUEUE_CONTENT_DELAY_5S: str = "ai.content.generate.delay_5s"

# Параметры транзитной очереди задержки (5000 мс)
DELAY_5S_TTL_MS: int = 5000

# Ограничение емкости DLQ кольцевого буфера (Ring Buffer)
DLQ_MAX_LENGTH: int = 10000


async def setup_rabbitmq_topology(channel: Any) -> None:
    """
    Декларирует полную AMQP-топологию с явным Direct Exchange, Ring Buffer DLQ и Policy-Ready очередями.

    1. Direct Exchange (ai.content.exchange):
       Централизованный маршрутизатор для всех сообщений контура.
    2. DLQ Ring Buffer (ai.content.generate.dlq):
       Лимит x-max-length=10000 и x-overflow="drop-head" (защита от Silent Dead-Letter Drop:
       вытесняются устаревшие инциденты, сохраняя самые свежие метрики отказов).
    3. Delay Queue (ai.content.generate.delay_5s):
       Транзитная очередь задержки (TTL 5s + возврат через EXCHANGE_NAME в requested).
    4. Requested Queue (ai.content.generate.requested):
       Zero-Arguments Policy-Ready декларация (durable=True без жестких arguments в Python),
       что исключает ошибку 406 PRECONDITION_FAILED при запуске на существующих инсталляциях.
       Правила DLX накладываются декларативно через RabbitMQ Policies.
    5. Completed Queue (ai.content.generate.completed):
       Очередь ответов, связанная с EXCHANGE_NAME.
    """
    logger.info(f"🔧 [Topology] Начало инициализации AMQP топологии (Exchange: '{EXCHANGE_NAME}')...")

    # 1. Декларация единого маршрутизатора (Explicit Exchange)
    exchange = await channel.declare_exchange(
        EXCHANGE_NAME,
        type="direct",
        durable=True
    )
    logger.info(f"✅ [Topology] Exchange '{EXCHANGE_NAME}' объявлен (type=direct, durable=True).")

    # 2. DLQ как кольцевой буфер (Ring Buffer с drop-head)
    dlq = await channel.declare_queue(
        QUEUE_CONTENT_DLQ,
        durable=True,
        arguments={
            "x-max-length": DLQ_MAX_LENGTH,
            "x-overflow": "drop-head"  # drop-head гарантирует сохранение свежих инцидентов ценой старых
        }
    )
    await dlq.bind(exchange, routing_key=QUEUE_CONTENT_DLQ)
    logger.info(
        f"✅ [Topology] DLQ Ring Buffer '{QUEUE_CONTENT_DLQ}' объявлена "
        f"(durable=True, max-length={DLQ_MAX_LENGTH}, overflow=drop-head) и привязана к '{EXCHANGE_NAME}'."
    )

    # 3. Транзитная очередь задержки
    delay_queue = await channel.declare_queue(
        QUEUE_CONTENT_DELAY_5S,
        durable=True,
        arguments={
            "x-message-ttl": DELAY_5S_TTL_MS,
            "x-dead-letter-exchange": EXCHANGE_NAME,
            "x-dead-letter-routing-key": QUEUE_CONTENT_REQUESTED
        }
    )
    await delay_queue.bind(exchange, routing_key=QUEUE_CONTENT_DELAY_5S)
    logger.info(
        f"✅ [Topology] Delay Queue '{QUEUE_CONTENT_DELAY_5S}' объявлена "
        f"(durable=True, TTL={DELAY_5S_TTL_MS}ms, DLX='{EXCHANGE_NAME}' -> '{QUEUE_CONTENT_REQUESTED}') "
        f"и привязана к '{EXCHANGE_NAME}'."
    )

    # 4. Основная очередь (Zero-Arguments Policy-Ready)
    # ВАЖНО: Аргументы удалены из Python-клиента. Параметры DLX накладываются ИСКЛЮЧИТЕЛЬНО
    # через RabbitMQ Policies, что гарантирует 100% защиту от ошибки 406 PRECONDITION_FAILED.
    requested_queue = await channel.declare_queue(
        QUEUE_CONTENT_REQUESTED,
        durable=True
    )
    await requested_queue.bind(exchange, routing_key=QUEUE_CONTENT_REQUESTED)
    logger.info(
        f"✅ [Topology] Requested Queue '{QUEUE_CONTENT_REQUESTED}' объявлена (Policy-Ready, durable=True) "
        f"и привязана к '{EXCHANGE_NAME}'."
    )

    # 5. Очередь ответов
    completed_queue = await channel.declare_queue(
        QUEUE_CONTENT_COMPLETED,
        durable=True
    )
    await completed_queue.bind(exchange, routing_key=QUEUE_CONTENT_COMPLETED)
    logger.info(
        f"✅ [Topology] Completed Queue '{QUEUE_CONTENT_COMPLETED}' объявлена (durable=True) "
        f"и привязана к '{EXCHANGE_NAME}'."
    )

    logger.info("🚀 [Topology] Полная топология AMQP успешно инициализирована и связана.")


async def init_topology_from_env(amqp_url: Optional[str] = None) -> None:
    """
    Вспомогательная функция для запуска из CLI / CI-CD с использованием aio_pika.
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

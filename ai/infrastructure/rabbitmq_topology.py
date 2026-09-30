"""
File: ai/infrastructure/rabbitmq_topology.py
AMQP Topology Bootstrapper: Истинный Zero-Arguments Policy-Ready бутстраппер
с явным Direct Exchange (ai.content.exchange), строгой статической типизацией
и полной делегацией мутирующих параметров в RabbitMQ Policies.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

try:
    import aio_pika
    import aio_pika.abc
    ChannelType = aio_pika.abc.AbstractChannel
except ImportError:
    # Fallback для окружений без aio_pika во время сборки/линтера
    ChannelType = object  # type: ignore

logger = logging.getLogger("RabbitMQTopology")

# Единый явный Direct Exchange контура AI
EXCHANGE_NAME: str = "ai.content.exchange"

# Названия очередей контура генерации контента
QUEUE_CONTENT_REQUESTED: str = "ai.content.generate.requested"
QUEUE_CONTENT_COMPLETED: str = "ai.content.generate.completed"
QUEUE_CONTENT_DLQ: str = "ai.content.generate.dlq"
QUEUE_CONTENT_DELAY_5S: str = "ai.content.generate.delay_5s"


async def setup_rabbitmq_topology(channel: ChannelType) -> None:
    """
    Декларирует физический каркас AMQP (Exchange, Queues, Bindings) в режиме True Zero-Arguments.
    
    1. Идемпотентность развертывания (Zero 406 PRECONDITION_FAILED):
       Все очереди объявляются исключительно с durable=True без словаря arguments.
       Любые мутирующие параметры (TTL, DLX, лимиты емкости) управляются на лету через RabbitMQ Policies.
    2. Явный Direct Exchange (ai.content.exchange):
       Обеспечивает 100% Observability и маршрутизацию всех потоков контура.
    """
    logger.info(f"🔧 [Topology] Инициализация физического каркаса AMQP (Exchange: '{EXCHANGE_NAME}')...")

    # 1. Декларация единого маршрутизатора (Explicit Direct Exchange)
    exchange = await channel.declare_exchange(
        EXCHANGE_NAME,
        type="direct",
        durable=True
    )
    logger.info(f"✅ [Topology] Exchange '{EXCHANGE_NAME}' объявлен (type=direct, durable=True).")

    # 2. DLQ (Поведенческая конфигурация ring-buffer делегирована в RabbitMQ Policies)
    dlq = await channel.declare_queue(
        QUEUE_CONTENT_DLQ,
        durable=True
    )
    await dlq.bind(exchange, routing_key=QUEUE_CONTENT_DLQ)
    logger.info(f"✅ [Topology] DLQ '{QUEUE_CONTENT_DLQ}' объявлена (Policy-Ready) и привязана к '{EXCHANGE_NAME}'.")

    # 3. Транзитная Delay-очередь (Поведенческая конфигурация TTL 5s + DLX делегирована в RabbitMQ Policies)
    delay_queue = await channel.declare_queue(
        QUEUE_CONTENT_DELAY_5S,
        durable=True
    )
    await delay_queue.bind(exchange, routing_key=QUEUE_CONTENT_DELAY_5S)
    logger.info(f"✅ [Topology] Delay Queue '{QUEUE_CONTENT_DELAY_5S}' объявлена (Policy-Ready) и привязана к '{EXCHANGE_NAME}'.")

    # 4. Основная очередь генерации (Поведенческая конфигурация DLX делегирована в RabbitMQ Policies)
    requested_queue = await channel.declare_queue(
        QUEUE_CONTENT_REQUESTED,
        durable=True
    )
    await requested_queue.bind(exchange, routing_key=QUEUE_CONTENT_REQUESTED)
    logger.info(f"✅ [Topology] Requested Queue '{QUEUE_CONTENT_REQUESTED}' объявлена (Policy-Ready) и привязана к '{EXCHANGE_NAME}'.")

    # 5. Очередь успешных/терминальных ответов
    completed_queue = await channel.declare_queue(
        QUEUE_CONTENT_COMPLETED,
        durable=True
    )
    await completed_queue.bind(exchange, routing_key=QUEUE_CONTENT_COMPLETED)
    logger.info(f"✅ [Topology] Completed Queue '{QUEUE_CONTENT_COMPLETED}' объявлена и привязана к '{EXCHANGE_NAME}'.")

    logger.info("🚀 [Topology] Инициализация топологии успешно завершена. Все мутирующие параметры делегированы в Policies.")


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

"""
File: tests/test_e2e_full_pipeline.py
Сквозной интеграционный тест (E2E): Happy Path, Transient Retry (Delay Queue) и Poison Message (DLQ).
"""

from __future__ import annotations

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from ai.workers.content_generation_worker import handle_generate_request
from ai.skills.content_generation_engine import ContentGenerationEngine
from ai.bridge.comfy_bridge import ComfyUIBridge, GPULoadBalancer


@pytest.mark.asyncio
async def test_e2e_happy_path_pipeline(
    rabbitmq_channel, 
    redis_client, 
    pg_db_pool, 
    comfy_bridge_mock
):
    """
    Сценарий 1: Happy Path (Генерация текста -> RAG -> Text Draft -> GPU Render -> Ready)
    """
    # 1. Публикация запроса в основную очередь через Exchange
    task_payload = {
        "task_id": 9991,
        "project_id": "estel_pro",
        "topic": "Маска Curex Therapy",
        "sku_id": "sku_curex_500ml",
        "connected_channels": ["telegram", "vk", "ok", "max_messenger"],
        "aspect_ratio": "1:1"
    }
    
    # 2. Эмуляция потребления воркером (ContentGenerationWorker)
    # Проверка выгрузки FactSheet через HNSW и Map-Reduce генерации с In-Flight Reflection
    mock_message = AsyncMock()
    mock_message.payload = task_payload
    mock_message.ack = AsyncMock()
    mock_message.nack = AsyncMock()

    content_engine = ContentGenerationEngine(dev_mode=True, concurrency_limit=1)

    await handle_generate_request(
        message=mock_message,
        redis_client=redis_client,
        message_broker=rabbitmq_channel,
        repository=pg_db_pool,
        content_engine=content_engine
    )
    
    # Ассерты Happy Path
    mock_message.ack.assert_awaited_once()
    mock_message.nack.assert_not_awaited()

    # Проверка фиксации статуса 'completed' в Redis (Stateful Tombstone)
    status = await redis_client.get("lock:task:9991:retry_0")
    assert status is not None
    assert status.decode("utf-8") == "completed"

    # Проверка отправки сообщения в очередь завершенных задач
    rabbitmq_channel.publish.assert_awaited_once()
    call_kwargs = rabbitmq_channel.publish.call_args.kwargs
    assert call_kwargs.get("routing_key") == "ai.content.generate.completed"
    assert call_kwargs.get("payload", {}).get("status") == "success"
    assert "bundle_data" in call_kwargs.get("payload", {})

    # 3. Эмуляция User Approval и Lazy Rendering через GPULoadBalancer
    gpu_pool = GPULoadBalancer(node_urls=["http://10.0.0.1:8188"])
    bridge = ComfyUIBridge(gpu_pool=gpu_pool)
    
    # В dev_simulation_mode=True bridge возвращает сгенерированный тестовый ассет без живой ноды
    asset_bytes = await bridge.render_asset(
        workflow_json={"workflow": "mock_json"},
        is_video=False,
        post_id="post_test_9991",
        dev_simulation_mode=True
    )
    assert isinstance(asset_bytes, bytes)
    assert len(asset_bytes) > 0


@pytest.mark.asyncio
async def test_e2e_transient_retry_delay_queue(redis_client, rabbitmq_channel, pg_db_pool):
    """
    Сценарий 2: Transient Retry / In-Flight Conflict -> Delay Queue (5s)
    """
    task_id = 9992
    lock_key = f"lock:task:{task_id}:retry_0"
    
    # Имитация активной задачи (status == 'processing')
    await redis_client.set(lock_key, "processing", ex=900)
    
    mock_message = AsyncMock()
    mock_message.payload = {"task_id": task_id, "project_id": "estel_pro", "retry_count": 0}
    mock_message.ack = AsyncMock()
    mock_message.nack = AsyncMock()

    content_engine = AsyncMock()

    # Повторная доставка во время активного инференса должна триггерить non-blocking offloading
    await handle_generate_request(
        message=mock_message,
        redis_client=redis_client,
        message_broker=rabbitmq_channel,
        repository=pg_db_pool,
        content_engine=content_engine
    )
    
    # Проверка отправки в delay-очередь с мгновенным ACK (освобождение префетча)
    mock_message.nack.assert_not_awaited()
    mock_message.ack.assert_awaited_once()

    # Проверка публикации в ai.content.generate.delay_5s
    rabbitmq_channel.publish.assert_awaited_once()
    call_kwargs = rabbitmq_channel.publish.call_args.kwargs
    assert call_kwargs.get("routing_key") == "ai.content.generate.delay_5s"
    assert call_kwargs.get("queue") == "ai.content.generate.delay_5s"


@pytest.mark.asyncio
async def test_e2e_poison_message_dlq_routing(redis_client, pg_db_pool):
    """
    Сценарий 3: Фатальный сбой транспорта -> Physical NACK -> DLQ (Ring Buffer drop-head)
    """
    task_id = 9993
    lock_key = f"lock:task:{task_id}:retry_0"

    mock_message = AsyncMock()
    mock_message.payload = {"task_id": task_id, "project_id": "estel_pro", "retry_count": 0}
    mock_message.ack = AsyncMock()
    mock_message.nack = AsyncMock()
    
    mock_broker = AsyncMock()
    # Эмуляция падения сокета при попытке отправить результат
    mock_broker.publish = AsyncMock(side_effect=ConnectionError("Broker socket dead"))

    content_engine = ContentGenerationEngine(dev_mode=True, concurrency_limit=1)

    await handle_generate_request(
        message=mock_message,
        redis_client=redis_client,
        message_broker=mock_broker,
        repository=pg_db_pool,
        content_engine=content_engine
    )
    
    # Проверка срабатывания Poison Message Guard: физический nack с requeue=False ДО записи tombstone
    mock_message.nack.assert_awaited_with(requeue=False)
    status = await redis_client.get(lock_key)
    assert status is not None
    assert status.decode("utf-8") == "dlq_routed"

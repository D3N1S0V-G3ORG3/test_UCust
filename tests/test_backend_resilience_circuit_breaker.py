"""
File: tests/test_backend_resilience_circuit_breaker.py
Тестирование модуля отказоустойчивости BackendAIResilienceClient:
- Circuit Breaker (CLOSED -> OPEN -> HALF_OPEN -> CLOSED)
- Мгновенный качественный Graceful Fallback без ожидания сети
- Корректность сборки MultiChannelPostBundle при полном отказе AI контура
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch

from ai.bridge.backend_resilience_client import BackendAIResilienceClient, CircuitState


@pytest.mark.asyncio
async def test_resilience_client_instant_fallback_on_failure():
    """
    Проверка применения мгновенного фоллбэка при недоступности AI Node.
    """
    client = BackendAIResilienceClient(
        ai_node_url="http://192.0.2.1:8000",  # Недостижимый IP
        failure_threshold=2,
        recovery_timeout_sec=1.0,
        request_timeout_sec=0.1
    )

    # 1-й запрос: падение -> фоллбэк
    bundle1, is_fallback1 = await client.generate_post_bundle(
        project_id="estel_pro",
        topic="Сыворотка Otium Aqua 50мл",
        target_channels=["telegram", "vk", "ok", "max_messenger"]
    )
    assert is_fallback1 is True
    assert len(bundle1.variants) == 4
    assert client.consecutive_failures == 1
    assert client.state == CircuitState.CLOSED

    # 2-й запрос: второе падение -> превышение порога -> переход в OPEN
    bundle2, is_fallback2 = await client.generate_post_bundle(
        project_id="estel_pro",
        topic="Маска Curex Therapy",
        target_channels=["telegram", "vk", "ok", "max_messenger"]
    )
    assert is_fallback2 is True
    assert client.state == CircuitState.OPEN

    # 3-й запрос: Circuit Breaker в состоянии OPEN (мгновенный ответ без попытки вызова сети)
    t0 = asyncio.get_event_loop().time()
    bundle3, is_fallback3 = await client.generate_post_bundle(
        project_id="estel_pro",
        topic="Шампунь Otium",
        target_channels=["telegram", "vk", "ok", "max_messenger"]
    )
    t_elapsed = asyncio.get_event_loop().time() - t0
    assert is_fallback3 is True
    assert t_elapsed < 0.05  # Меньше 50мс!
    assert client.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_resilience_client_circuit_recovery():
    """
    Проверка автоматического восстановления (OPEN -> HALF_OPEN -> CLOSED).
    """
    client = BackendAIResilienceClient(
        ai_node_url="http://mock-ai:8000",
        failure_threshold=1,
        recovery_timeout_sec=0.2,
        request_timeout_sec=0.1
    )

    # Загоняем в OPEN
    await client.generate_post_bundle(project_id="test", topic="Test")
    assert client.state == CircuitState.OPEN

    # Ждем таймаут восстановления
    await asyncio.sleep(0.3)

    # Эмулируем успешный ответ AI-сервиса
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json = lambda: {
        "status": "success",
        "data": {
            "brand_id": "test",
            "topic": "Test Live",
            "active_channels": ["telegram"],
            "variants": {
                "telegram": {
                    "post_id": "p1",
                    "brand_id": "test",
                    "target_date": "2026-09-30T00:00:00Z",
                    "format": "single_shot",
                    "status": "draft_text",
                    "target_channel": "telegram",
                    "text_content": "<b>Живой текст от восстановленного AI</b>",
                    "channel_payload": {"parse_mode": "HTML"},
                    "image_specs": [],
                    "rendered_image_urls": [],
                    "vram_cost_mb": 0
                }
            }
        }
    }

    with patch("httpx.AsyncClient.post", return_value=mock_response):
        bundle, is_fallback = await client.generate_post_bundle(
            project_id="test",
            topic="Test Live",
            target_channels=["telegram"]
        )
        assert is_fallback is False
        assert client.state == CircuitState.CLOSED
        assert client.consecutive_failures == 0
        assert "Живой текст" in bundle.variants["telegram"].text_content

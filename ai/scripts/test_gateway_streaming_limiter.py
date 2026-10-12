"""
File: ai/scripts/test_gateway_streaming_limiter.py
Интеграционный тест-сьют для:
1. Pydantic v2 схемы PipelineEvent и SSE wire-format сериализации.
2. DistributedPipelineEventBus: публикация, подписка, Last-Event-ID history replay, завершение стрима.
3. RedisTokenBucketRateLimiter: списание токенов, истощение лимита, retry-after расчет.
4. ConcurrencyLimiter: захват слотов параллельной генерации, отсечение избыточных задач.
5. FastAPI эндпоинт SSE стриминга: заголовки text/event-stream, X-Accel-Buffering, keep-alive.
6. RateLimitGuard dependency: возврат HTTP 429 Too Many Requests при превышении RPS.
7. Интеграция PipelineOrchestratorFacade.execute_pipeline с живой эмиссией событий в EventBus.
"""

import os
import sys
import json
import time
import asyncio
from typing import List

# Setup sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from fastapi.testclient import TestClient
from api_gateway import app
from api.streaming import PipelineEvent, DistributedPipelineEventBus, global_event_bus
from api.rate_limiter import RedisTokenBucketRateLimiter, ConcurrencyLimiter, RateLimitGuard
from schemas.pipeline_state import PipelineState, ContentFormatEnum
from core.orchestrator import UnifiedOrchestrator


async def test_pipeline_event_schema():
    print("\n--- 1. Testing PipelineEvent Schema & SSE Formatting ---")
    event = PipelineEvent(
        event_id="evt_test_101",
        event_type="step_progress",
        session_id="sess_abc",
        stage="brand_dna",
        progress_pct=25,
        message="Извлечение профиля компании...",
        payload={"field": "retail"}
    )
    sse_wire = event.to_sse_format()
    assert "id: evt_test_101\n" in sse_wire
    assert "event: step_progress\n" in sse_wire
    assert "data: {" in sse_wire
    assert '"progress_pct": 25' in sse_wire
    assert sse_wire.endswith("\n\n")
    print("   [OK] PipelineEvent Pydantic v2 schema validated & SSE wire format verified.")


async def test_event_bus_pub_sub_and_replay():
    print("\n--- 2. Testing DistributedPipelineEventBus (Pub/Sub & Last-Event-ID) ---")
    bus = DistributedPipelineEventBus()
    test_session = f"test_session_{int(time.time())}"

    # Публикуем 3 события в историю
    e1 = PipelineEvent(event_id="e1", event_type="step_started", session_id=test_session, stage="brand_dna", progress_pct=10, message="Шаг 1")
    e2 = PipelineEvent(event_id="e2", event_type="step_progress", session_id=test_session, stage="content_draft", progress_pct=50, message="Шаг 2")
    e3 = PipelineEvent(event_id="e3", event_type="pipeline_finished", session_id=test_session, stage="critic_review", progress_pct=100, message="Финиш")

    await bus.publish_event(e1)
    await bus.publish_event(e2)
    await bus.publish_event(e3)

    # Тест 2.1: Полное чтение истории
    received_full: List[str] = []
    async for frame in bus.subscribe_stream(session_id=test_session):
        received_full.append(frame)
    assert len(received_full) == 3
    assert "id: e1\n" in received_full[0]
    assert "id: e2\n" in received_full[1]
    assert "id: e3\n" in received_full[2]
    print(f"   [OK] Полное чтение истории: получено {len(received_full)} фреймов.")

    # Тест 2.2: Last-Event-ID replay (клиент пропустил только e3)
    received_replay: List[str] = []
    async for frame in bus.subscribe_stream(session_id=test_session, last_event_id="e2"):
        received_replay.append(frame)
    assert len(received_replay) == 1
    assert "id: e3\n" in received_replay[0]
    print(f"   [OK] Replay с Last-Event-ID='e2': отсечены e1 и e2, воспроизведен только e3.")

    # Тест 2.3: Живой стрим (асинхронная публикация во время прослушивания)
    live_session = f"live_session_{int(time.time())}"
    live_frames: List[str] = []

    async def consumer():
        async for frame in bus.subscribe_stream(session_id=live_session, heartbeat_interval_sec=5.0):
            if frame.startswith(":"):
                continue  # ignore heartbeat
            live_frames.append(frame)
            if "pipeline_finished" in frame:
                break

    consumer_task = asyncio.create_task(consumer())
    await asyncio.sleep(0.05)  # дать время на регистрацию очереди

    await bus.publish_event(PipelineEvent(event_id="live_1", event_type="step_started", session_id=live_session, stage="brand_dna", progress_pct=10, message="Старт"))
    await bus.publish_event(PipelineEvent(event_id="live_2", event_type="pipeline_finished", session_id=live_session, stage="publishing", progress_pct=100, message="Конец"))

    await asyncio.wait_for(consumer_task, timeout=2.0)
    assert len(live_frames) == 2
    assert "id: live_1\n" in live_frames[0]
    assert "id: live_2\n" in live_frames[1]
    print(f"   [OK] Живой Pub/Sub стрим: успешно доставлено {len(live_frames)} событий подписчику.")


async def test_token_bucket_rate_limiter():
    print("\n--- 3. Testing RedisTokenBucketRateLimiter ---")
    limiter = RedisTokenBucketRateLimiter()
    key = f"tenant_test_{int(time.time())}"

    # Конфигурация: capacity=3 токена, refill=1 токен в секунду
    allowed1, rem1, retry1 = await limiter.check_rate_limit(key=key, refill_rate=1.0, capacity=3, requested=1)
    allowed2, rem2, retry2 = await limiter.check_rate_limit(key=key, refill_rate=1.0, capacity=3, requested=1)
    allowed3, rem3, retry3 = await limiter.check_rate_limit(key=key, refill_rate=1.0, capacity=3, requested=1)

    assert allowed1 is True
    assert allowed2 is True
    assert allowed3 is True
    assert rem3 == 0
    print(f"   [OK] Первые 3 запроса разрешены (capacity исчерпан, остаток: {rem3}).")

    # 4-й запрос должен быть заблокирован (Burst исчерпан)
    allowed4, rem4, retry4 = await limiter.check_rate_limit(key=key, refill_rate=1.0, capacity=3, requested=1)
    assert allowed4 is False
    assert retry4 >= 1
    print(f"   [OK] 4-й запрос отклонен: allowed=False, retry_after={retry4}s.")


async def test_concurrency_limiter():
    print("\n--- 4. Testing ConcurrencyLimiter ---")
    limiter = ConcurrencyLimiter()
    c_key = f"concurrency_user_{int(time.time())}"

    # Лимит 2 параллельные генерации
    s1 = await limiter.acquire(c_key, max_concurrent=2)
    s2 = await limiter.acquire(c_key, max_concurrent=2)
    s3 = await limiter.acquire(c_key, max_concurrent=2)

    assert s1 is True
    assert s2 is True
    assert s3 is False  # 3-й слот отклонен
    print("   [OK] Слоты 1 и 2 захвачены, слот 3 успешно отклонен Concurrency Guard.")

    # Освобождаем один слот
    await limiter.release(c_key)
    s4 = await limiter.acquire(c_key, max_concurrent=2)
    assert s4 is True
    print("   [OK] После release слот успешно перезахвачен.")
    await limiter.release(c_key)
    await limiter.release(c_key)


def test_fastapi_sse_and_rate_limit():
    print("\n--- 5. Testing FastAPI SSE Endpoint & RateLimitGuard ---")
    client = TestClient(app)

    # 5.1 Проверка эндпоинта стриминга
    session_id = f"http_stream_test_{int(time.time())}"
    # Публикуем событие в глобальную шину
    asyncio.run(global_event_bus.publish_event(
        PipelineEvent(event_id="h1", event_type="pipeline_finished", session_id=session_id, stage="completed", progress_pct=100, message="Готово")
    ))

    resp = client.get(f"/api/v1/pipeline/stream/{session_id}")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    assert resp.headers.get("x-accel-buffering") == "no"
    assert "id: h1" in resp.text
    print("   [OK] GET /api/v1/pipeline/stream/{id} вернул корректный SSE stream с заголовками Nginx no-buffer.")

    # 5.2 Проверка RateLimitGuard (HTTP 429) на тяжелом эндпоинте
    import jwt
    from api.dependencies.auth import JWT_SECRET, JWT_ALGORITHM
    t_id = f"heavy_tenant_{int(time.time())}"
    token = jwt.encode({"tenant_id": t_id, "exp": time.time() + 3600}, JWT_SECRET, algorithm=JWT_ALGORITHM)
    tenant_headers = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-ID": t_id
    }
    payload = {"prompt": "Тест лимитера", "tier": "business"}

    # Первый запрос успешен (HTTP 202)
    r1 = client.post("/api/v1/content/generate-async", json=payload, headers=tenant_headers)
    assert r1.status_code == 202
    assert "x-ratelimit-limit" in r1.headers
    assert int(r1.headers["x-ratelimit-limit"]) == 20
    print(f"   [OK] HTTP Headers RateLimit присутствуют: Limit={r1.headers.get('x-ratelimit-limit')}, Remaining={r1.headers.get('x-ratelimit-remaining')}")

    # Быстрый цикл исчерпания capacity (20 токенов)
    exhausted_response = None
    for _ in range(25):
        resp_test = client.post("/api/v1/content/generate-async", json=payload, headers=tenant_headers)
        if resp_test.status_code == 429:
            exhausted_response = resp_test
            break

    assert exhausted_response is not None
    assert exhausted_response.status_code == 429
    assert "retry-after" in exhausted_response.headers
    print(f"   [OK] Превышение лимита запросов: вернулся HTTP 429 Too Many Requests (Retry-After: {exhausted_response.headers.get('retry-after')}s)")


async def test_orchestrator_sse_emission_e2e():
    print("\n--- 6. Testing End-to-End Orchestrator Pipeline SSE Emission ---")
    orchestrator = UnifiedOrchestrator()
    session_id = f"e2e_sse_{int(time.time())}"

    state = PipelineState(
        session_id=session_id,
        tenant_id="tenant_sse_test",
        user_id="user_sse",
        company_name="Quantum Cloud",
        niche="Cloud Computing",
        topic="Масштабирование распределенных систем",
        target_format=ContentFormatEnum.POST,
    )

    # Запускаем конвейер
    final_state = await orchestrator.execute_pipeline(state, auto_publish=False)
    assert final_state.draft_text != ""

    # Проверяем, что события зафиксировались в DistributedPipelineEventBus
    captured_events: List[str] = []
    async for frame in global_event_bus.subscribe_stream(session_id=session_id):
        captured_events.append(frame)

    assert len(captured_events) >= 4
    # Проверяем наличие всех ключевых этапов
    all_frames_text = "".join(captured_events)
    assert "brand_dna" in all_frames_text
    assert "content_draft" in all_frames_text
    assert "critic_review" in all_frames_text
    assert "pipeline_finished" in all_frames_text

    print(f"   [OK] Orchestrator сквозной пайплайн опубликовал {len(captured_events)} событий в SSE шину.")
    print("      Этапы:", ["brand_dna", "content_draft", "critic_review", "pipeline_finished"])


def main():
    print("=" * 70)
    print("🚀 RUNNING API GATEWAY HARDENING & SSE STREAMING TEST SUITE")
    print("=" * 70)

    asyncio.run(test_pipeline_event_schema())
    asyncio.run(test_event_bus_pub_sub_and_replay())
    asyncio.run(test_token_bucket_rate_limiter())
    asyncio.run(test_concurrency_limiter())
    test_fastapi_sse_and_rate_limit()
    asyncio.run(test_orchestrator_sse_emission_e2e())

    print("\n" + "=" * 70)
    print("🎉 ALL 6 API GATEWAY & STREAMING TEST SUITES PASSED SUCCESSFULLY (100%)")
    print("=" * 70)


if __name__ == "__main__":
    main()

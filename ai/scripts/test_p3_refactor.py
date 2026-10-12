# File: ai/scripts/test_p3_refactor.py
"""
test_p3_refactor.py
Validation test suite for Phase P3 Refactoring:
1. Circuit Breaker state transitions (CLOSED -> OPEN -> HALF_OPEN -> CLOSED) and retries
2. Unified BasePublisher interface and concrete publishers (AchievementBroadcaster, Telegram, VK)
3. Structured JSON logging (ELK / Grafana Loki compatible) and token/cost telemetry
4. RedisCacheManager bounded TTL and memory-leak prevention (bounded LRU fallback)
"""

import os
import sys
import json
import time
import asyncio
import logging

# Setup sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from core.resilience import (
    CircuitBreaker,
    CircuitState,
    CircuitBreakerOpenException,
    CircuitBreakerRegistry,
    retry_with_backoff,
)
from publishers.base import BasePublisher
from publishers.achievement_broadcaster import AchievementBroadcaster
from publishers.telegram import TelegramPublisher
from publishers.vk import VkPublisher
from core.redis_cache import RedisCacheManager
from core.observability import ObservabilityManager
from core.orchestrator import PipelineOrchestratorFacade, UnifiedOrchestrator
from schemas.pipeline_state import PipelineState, ContentFormatEnum


async def test_circuit_breaker_transitions():
    print("\n--- 1. Testing Circuit Breaker State Transitions ---")
    cb = CircuitBreaker(
        name="test_cb",
        failure_threshold=2,
        recovery_timeout=0.3
    )


    assert cb.state == CircuitState.CLOSED, f"Initial state must be CLOSED, got {cb.state}"
    print("  [Pass] Initial state is CLOSED")

    call_count = 0

    async def faulty_task():
        nonlocal call_count
        call_count += 1
        raise ConnectionError("Service unreachable")

    # Attempt 1: failure
    try:
        await cb.call(faulty_task)
    except ConnectionError:
        pass
    assert cb.state == CircuitState.CLOSED, f"After 1 failure, state should still be CLOSED, got {cb.state}"
    assert cb.failure_count == 1
    print("  [Pass] State remains CLOSED after 1 failure (threshold=2)")

    # Attempt 2: second failure -> should trip to OPEN
    try:
        await cb.call(faulty_task)
    except ConnectionError:
        pass
    assert cb.state == CircuitState.OPEN, f"After 2 failures, state must be OPEN, got {cb.state}"
    print("  [Pass] Circuit tripped to OPEN after reaching failure threshold")

    # Fast-fail check: underlying function must NOT be called when OPEN
    recorded_calls = call_count
    try:
        await cb.call(faulty_task)
        assert False, "Should have raised CircuitBreakerOpenException"
    except CircuitBreakerOpenException:
        print("  [Pass] Fast-fail: CircuitBreakerOpenException raised without calling underlying task")
    assert call_count == recorded_calls, "Faulty task must not have been executed while OPEN"

    # Fallback support check
    fallback_result = await cb.call(faulty_task, fallback=lambda: {"fallback": True})
    assert fallback_result == {"fallback": True}
    print("  [Pass] Fallback executed smoothly when Circuit is OPEN")

    # Wait for recovery timeout
    print("  Waiting 0.35s for recovery timeout...")
    await asyncio.sleep(0.35)

    assert cb.state == CircuitState.HALF_OPEN, f"State should have transitioned to HALF_OPEN, got {cb.state}"
    print("  [Pass] Circuit transitioned to HALF_OPEN after recovery timeout")

    # Successful call in HALF_OPEN -> reset to CLOSED
    async def healthy_task():
        return "success"

    res = await cb.call(healthy_task)
    assert res == "success"
    assert cb.state == CircuitState.CLOSED, f"State should be CLOSED after recovery, got {cb.state}"
    assert cb.failure_count == 0
    print("  [Pass] Successful call in HALF_OPEN reset Circuit to CLOSED")


async def test_unified_publishers():
    print("\n--- 2. Testing Unified BasePublisher & Implementations ---")

    # Concrete mock publisher for testing base class
    class MockPublisher(BasePublisher):
        platform_name = "mock_social"

        def __init__(self, should_fail=False):
            super().__init__(target_channel="@mock_chan", failure_threshold=2, recovery_timeout=0.2)
            self.should_fail = should_fail
            self.executions = 0

        async def _execute_publish(self, text, media_path=None, **kwargs):
            self.executions += 1
            if self.should_fail:
                raise TimeoutError("Mock API timeout")
            return {
                "status": "success",
                "platform": self.platform_name,
                "channel": self.target_channel,
                "text_len": len(text)
            }

    pub = MockPublisher()
    res = await pub.publish("Hello World", media_path=None)
    assert res["status"] == "success"
    assert res["platform"] == "mock_social"
    assert res["channel"] == "@mock_chan"
    print("  [Pass] BasePublisher._execute_publish works correctly via .publish()")

    # Test error handling and Circuit Breaker integration
    failing_pub = MockPublisher(should_fail=True)
    err_res1 = await failing_pub.publish("Fail 1")
    assert err_res1["status"] == "error"
    err_res2 = await failing_pub.publish("Fail 2")
    assert err_res2["status"] == "error"
    # Circuit should now be open
    assert failing_pub.circuit_breaker.state == CircuitState.OPEN
    err_res3 = await failing_pub.publish("Fail 3")
    assert err_res3["status"] == "error"
    assert "Circuit Breaker" in err_res3["error"]
    print("  [Pass] BasePublisher handles errors and trips Circuit Breaker cleanly")

    # Check inheritance of production publishers
    assert issubclass(AchievementBroadcaster, BasePublisher), "AchievementBroadcaster must inherit BasePublisher"
    assert issubclass(TelegramPublisher, BasePublisher), "TelegramPublisher must inherit BasePublisher"
    assert issubclass(VkPublisher, BasePublisher), "VkPublisher must inherit BasePublisher"
    print("  [Pass] AchievementBroadcaster, TelegramPublisher, and VkPublisher inherit BasePublisher")

    # Test concrete publishers instantiate and have circuit_breaker
    broadcaster = AchievementBroadcaster(target_channel="@test_broadcaster")
    assert broadcaster.circuit_breaker is not None
    assert broadcaster.platform_name == "telegram"
    print("  [Pass] AchievementBroadcaster has active Circuit Breaker and correct platform")

    tg = TelegramPublisher(target_channel="@test_tg")
    assert tg.circuit_breaker is not None
    assert tg.platform_name == "telegram"
    tg_pub_res = await tg.publish("Тестовый пост для Telegram")
    assert tg_pub_res["status"] == "success"
    print("  [Pass] TelegramPublisher.publish returns structured dict through BasePublisher")

    vk = VkPublisher(group_id="test_vk_club")
    assert vk.circuit_breaker is not None
    assert vk.platform_name == "vk"
    vk_pub_res = await vk.publish("Тестовый пост для VK")
    assert vk_pub_res["status"] == "success"
    print("  [Pass] VkPublisher.publish returns structured dict through BasePublisher")


def test_redis_cache_ttl_and_bounded_fallback():
    print("\n--- 3. Testing RedisCacheManager Bounded TTL & Fallback Cache ---")
    cache = RedisCacheManager(max_fallback_size=3)

    # 1. Test bounded size (LRU eviction)
    cache.set_cached_result("action1", "hash1", {"data": 1}, ttl=3600)
    cache.set_cached_result("action2", "hash2", {"data": 2}, ttl=3600)
    cache.set_cached_result("action3", "hash3", {"data": 3}, ttl=3600)
    assert len(cache._fallback_cache) == 3
    print("  [Pass] Added 3 items up to max_fallback_size=3")

    # Adding 4th item should evict oldest (action1)
    cache.set_cached_result("action4", "hash4", {"data": 4}, ttl=3600)
    assert len(cache._fallback_cache) <= 3, f"Cache size exceeded cap: {len(cache._fallback_cache)}"
    assert cache.get_cached_result("action1", "hash1") is None, "action1 should have been evicted"
    assert cache.get_cached_result("action4", "hash4") == {"data": 4}
    print("  [Pass] Oldest item evicted when capacity exceeded (No memory leak)")

    # 2. Test TTL expiration
    cache.set_cached_result("short_lived", "hash_short", {"expire": True}, ttl=1)
    assert cache.get_cached_result("short_lived", "hash_short") == {"expire": True}
    print("  Waiting 1.1s for TTL expiration...")
    time.sleep(1.1)
    expired_val = cache.get_cached_result("short_lived", "hash_short")
    assert expired_val is None, "Expired item should return None"
    print("  [Pass] Item expired and was evicted based on TTL")

    # 3. Test RAG query caching
    query = "Какие услуги предоставляет компания?"
    tenant = "tenant_marketing"
    rag_data = {"context": "Компания занимается автоматизацией ИИ-маркетинга", "has_context": True}

    cache.set_cached_rag_query(query, tenant_id=tenant, result=rag_data, ttl=14400)
    cached_rag = cache.get_cached_rag_query(query, tenant_id=tenant)
    assert cached_rag == rag_data
    assert cache.get_cached_rag_query(query, tenant_id="other_tenant") is None, "Tenant isolation in RAG cache failed"
    print("  [Pass] RAG query cached with tenant isolation and 4-hour bounded TTL")


async def test_structured_logging_and_telemetry():
    print("\n--- 4. Testing Structured JSON Logging & Telemetry ---")

    # Capture logs emitted by PipelineOrchestratorFacade
    captured_logs = []

    class MemoryLogHandler(logging.Handler):
        def emit(self, record):
            captured_logs.append(self.format(record))

    handler = MemoryLogHandler()
    logger = logging.getLogger("PipelineOrchestratorFacade")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    facade = PipelineOrchestratorFacade()

    state = PipelineState(
        session_id="test-p3-telemetry-session",
        tenant_id="tenant_p3",
        company_name="AutoBiz",
        topic="Запуск ИИ-ассистента",
        target_format=ContentFormatEnum.POST,
    )

    user_data = {
        "company_name": "AutoBiz",
        "topic": "Запуск ИИ-ассистента",
        "target_format": "post"
    }

    # Execute pipeline
    final_state = await facade.execute_pipeline(state, user_data=user_data, auto_publish=False)

    # 1. Telemetry checks
    assert "total_pipeline_duration" in final_state.telemetry
    assert "token_consumption" in final_state.telemetry
    assert "cost_usd" in final_state.telemetry

    tokens = final_state.telemetry["token_consumption"]
    assert "prompt_tokens" in tokens
    assert "completion_tokens" in tokens
    assert "total_tokens" in tokens
    assert tokens["total_tokens"] > 0
    assert final_state.telemetry["cost_usd"] >= 0.0
    print(f"  [Pass] Telemetry computed: duration={final_state.telemetry['total_pipeline_duration']}s, tokens={tokens['total_tokens']}, cost=${final_state.telemetry['cost_usd']}")

    # 2. Structured JSON Log verification
    json_log_found = False
    for log_msg in captured_logs:
        try:
            parsed = json.loads(log_msg)
            if parsed.get("event") == "pipeline_execution_completed":
                json_log_found = True
                assert parsed["session_id"] == "test-p3-telemetry-session"
                assert parsed["tenant_id"] == "tenant_p3"
                assert parsed["company_name"] == "AutoBiz"
                assert parsed["status"] == "success"
                assert "token_consumption" in parsed
                assert "cost_estimation_usd" in parsed
                assert "total_duration_sec" in parsed
                print("  [Pass] Structured JSON Log verified (ELK/Grafana Loki compliant):")
                print("         " + json.dumps(parsed, ensure_ascii=False)[:120] + "...")
                break
        except json.JSONDecodeError:
            continue

    assert json_log_found, "Structured JSON log for pipeline_execution_completed was not found in logs!"

    # 3. Test execute_task with RAG caching
    rag_query_res = await facade.execute_task("rag_query", {
        "query": "Наши ключевые преимущества",
        "tenant_id": "tenant_p3"
    })
    assert rag_query_res["status"] == "success"

    # Second call should be retrieved from cache
    rag_cached_res = await facade.execute_task("rag_query", {
        "query": "Наши ключевые преимущества",
        "tenant_id": "tenant_p3"
    })
    assert rag_cached_res.get("cached") is True
    print("  [Pass] execute_task('rag_query') successfully uses RedisCacheManager with TTL")

    logger.removeHandler(handler)


async def main():
    print("=" * 70)
    print("🚀 RUNNING PHASE P3 RESILIENCE, OBSERVABILITY & CACHE TEST SUITE")
    print("=" * 70)

    await test_circuit_breaker_transitions()
    await test_unified_publishers()
    test_redis_cache_ttl_and_bounded_fallback()
    await test_structured_logging_and_telemetry()

    print("\n" + "=" * 70)
    print("🏆 ALL PHASE P3 TESTS PASSED SUCCESSFULLY! (100% SUCCESS RATE)")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())

"""
Integration Test Suite: Feedback Loop Engine, Continuous Learning, Echo-Chamber Guard & Critic Penalization
Tests:
1. SaigaLLMSkill Echo-Chamber Guard prompt injection with proven_hooks.
2. CriticMungerSkill mandatory penalization and rejection for negative_constraints.
3. Celery collect_channel_telemetry_batch_task under CircuitBreaker with RAG sync.
4. End-to-end CampaignService integration with negative constraint detection and PipelineState rejection.
"""

from __future__ import annotations
import sys
import os
import asyncio
from datetime import datetime

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Add parent path to sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from schemas.pipeline_state import PipelineState, ContentFormatEnum
from schemas.feedback_state import (
    PostTelemetryEvent, TelemetryMetrics, GenerationMetadataLink, PerformanceTierEnum
)
from analytics.feedback_loop_engine import FeedbackLoopEngine
from skills.critic_munger import CriticMungerSkill
from skills.saiga_llm import SaigaLLMSkill
from services.campaign_service import CampaignService
from rag.pipeline import CleanRAGPipeline
from rag.models import Document
from core.resilience import CircuitBreaker, CircuitBreakerOpenException
from celery_tasks import collect_channel_telemetry_batch_task, enqueue_telemetry_batch_task


def test_saiga_echo_chamber_guard():
    print("\n" + "="*70)
    print("▶ TEST 1: Saiga LLM Echo-Chamber Guard Prompt Injection")
    print("="*70)

    saiga = SaigaLLMSkill()
    proven_hooks = [
        {
            "type": "proven_hook",
            "hook": "Почему 90% предпринимателей теряют время на рутине? Разбираем 3 неочевидные ошибки.",
            "target_format": "post",
            "normalized_score": 0.88,
        },
        {
            "type": "proven_hook",
            "hook": "Чек-лист автоматизации 2026: как сократить издержки без потери качества.",
            "target_format": "post",
            "normalized_score": 0.82,
        }
    ]

    res = saiga.generate_smm_post(
        topic="Автоматизация складского учета для логистических хабов",
        company_name="ЛогистПро",
        niche="Логистика и склад",
        proven_hooks=proven_hooks,
    )

    assert "post_text" in res, "generate_smm_post must return post_text"
    assert hasattr(saiga, "_last_proven_hooks_info"), "Saiga must store _last_proven_hooks_info"
    
    hooks_info = saiga._last_proven_hooks_info
    print(f"Captured Echo-Chamber Guard Prompt:\n{hooks_info}")

    assert "ПАТТЕРНЫ ВЫСОКОГО ОТКЛИКА АУДИТОРИИ (ECHO-CHAMBER GUARD & CONTINUOUS LEARNING)" in hooks_info
    assert "не копируя слова и сущности из примеров" in hooks_info
    assert "Почему 90% предпринимателей теряют время" in hooks_info
    assert "Чек-лист автоматизации 2026" in hooks_info

    print("✅ TEST 1 PASSED: Saiga correctly injected proven_hooks with Echo-Chamber Guard instructions.")


def test_critic_munger_negative_constraint_penalization():
    print("\n" + "="*70)
    print("▶ TEST 2: Charlie Munger Critic 2.0 Mandatory Negative Constraint Penalization")
    print("="*70)

    critic = CriticMungerSkill(strictness=0.80)

    failed_pattern = "Шок! Вы никогда не догадаетесь, как дешево купить наши услуги прямо сейчас!"
    negative_constraints = [
        {
            "type": "negative_constraint",
            "failed_hook": failed_pattern,
            "critic_penalty": 0.40,
            "reason": "Кликбейтный заголовок с аномально низким ER (0.12%) и высоким оттоком.",
        }
    ]

    # Черновик, воспроизводящий провальный паттерн (сходство ключевых слов)
    bad_draft = (
        "Шок! Вы никогда не догадаетесь, как дешево заказать автоматизацию в нашей компании прямо сейчас!\n\n"
        "Мы предлагаем надежное решение задач складского учета и интеграцию современных систем 2026 года.\n"
        "Оставьте заявку и получите бесплатную консультацию эксперта."
    )

    review = critic.review_content(
        text=bad_draft,
        topic="Автоматизация склада",
        niche="B2B автоматизация",
        negative_constraints=negative_constraints,
    )

    print(f"Critic Score: {review['score']}")
    print(f"Passed: {review['passed']}")
    print(f"Verdict: {review['verdict']}")
    print(f"Criticism: {review['criticism']}")
    print(f"Actionable Feedback: {review['actionable_feedback']}")
    print(f"Fatal Flaws: {review['fatal_flaws']}")

    # Должен быть отклонен со штрафом
    assert review["passed"] is False, "Draft with negative constraint must be REJECTED!"
    assert review["verdict"] == "REVISE_NEEDED", "Verdict must be REVISE_NEEDED"
    assert review["score"] < 0.50, f"Score ({review['score']}) must be strictly penalized below 0.50"
    assert review["audit_breakdown"].get("feedback_constraint") is False, "audit_breakdown['feedback_constraint'] must be False"
    assert any("Feedback Negative Constraint" in flaw for flaw in review["fatal_flaws"]), "Fatal flaw must report negative constraint"
    assert "ПРИНУДИТЕЛЬНЫЙ ОТСЕВ" in review["actionable_feedback"], "Actionable feedback must contain mandatory purge directive"

    print("✅ TEST 2 PASSED: Critic Munger mathematically penalized draft score to < 0.50 and rejected the post.")


def test_celery_channel_batch_telemetry():
    print("\n" + "="*70)
    print("▶ TEST 3: Celery Channel Telemetry Batch Task & RAG Sync")
    print("="*70)

    # 1. Формируем пакет телеметрии канала (1 успешный пост, 1 провальный пост)
    batch_mock = [
        {
            "tenant_id": "tenant_test_1",
            "session_id": "sess_high_er",
            "post_id": "post_high_101",
            "channel": "@tech_hub",
            "platform": "telegram",
            "snapshot_window": "24h",
            "metrics": {
                "views": 2000,
                "likes": 180,
                "reposts": 80,
                "bookmarks": 90,
                "comments_count": 45,
                "dislikes": 0,
            },
            "generation_context": {
                "target_format": "post",
                "prompt_topic": "Архитектура мультиагентных систем",
                "draft_snippet": "Как 3 автономных ИИ-агента ускоряют разработку в 5 раз: подробный разбор пайплайна.",
            }
        },
        {
            "tenant_id": "tenant_test_1",
            "session_id": "sess_low_er",
            "post_id": "post_low_202",
            "channel": "@tech_hub",
            "platform": "telegram",
            "snapshot_window": "24h",
            "metrics": {
                "views": 3000,
                "likes": 5,
                "reposts": 0,
                "bookmarks": 1,
                "comments_count": 0,
                "dislikes": 10,
            },
            "generation_context": {
                "target_format": "post",
                "prompt_topic": "Быстрые скидки на наш софт",
                "draft_snippet": "Только сегодня! Скидка 99% на всё, успейте купить!",
            }
        }
    ]

    res = collect_channel_telemetry_batch_task(
        channel="@tech_hub",
        platform="telegram",
        tenant_id="tenant_test_1",
        batch_limit=50,
        mock_events=batch_mock,
    )

    print(f"Batch Execution Result: {res}")
    assert res["status"] == "success"
    assert res["processed_count"] == 2
    assert res["proven_hooks_count"] == 1, "Must generate exactly 1 proven hook from high ER"
    assert res["negative_constraints_count"] == 1, "Must generate exactly 1 negative constraint from low ER"
    assert res["rag_indexed_chunks"] >= 2, "Both directives must be indexed in Clean RAG"
    assert res["circuit_breaker"]["state"].lower() == "closed"

    # 2. Проверка Circuit Breaker tripping
    cb = CircuitBreaker("test_cb_trip", failure_threshold=2, recovery_timeout=5.0)
    for _ in range(2):
        cb.record_failure(Exception("Social API 500 error"))
    assert cb.state.value.lower() == "open", "CircuitBreaker must be OPEN after threshold failures"

    # Enqueue test
    enqueue_res = enqueue_telemetry_batch_task(
        channel="@tech_hub",
        platform="telegram",
        tenant_id="tenant_test_1",
        batch_limit=50,
    )
    assert enqueue_res["status"] == "QUEUED"
    assert enqueue_res["queue"] == "feedback_loop"

    print("✅ TEST 3 PASSED: Channel batch task processed telemetry, extracted proven hooks/negative constraints, indexed into RAG, and verified CircuitBreaker.")


async def test_end_to_end_campaign_feedback_loop():
    print("\n" + "="*70)
    print("▶ TEST 4: End-to-End CampaignService Integration & Rejection")
    print("="*70)

    rag = CleanRAGPipeline()
    # Индексируем в RAG негативное ограничение для tenant_demo
    bad_hook_phrase = "Невероятный прорыв в сфере бизнеса только у нас"
    neg_doc = Document(
        doc_id="neg_constraint_demo_1",
        text=f"Негативное ограничение редполитики: Запрещено использовать клише '{bad_hook_phrase}'. Причина: Низкий ER 0.1%.",
        metadata={
            "type": "negative_constraint",
            "tenant_id": "tenant_e2e_demo",
            "target_format": "post",
            "penalty": 0.35,
            "failed_hook": bad_hook_phrase,
            "reason": "Исторически неэффективный паттерн с ER 0.1%",
        }
    )
    await rag.ingest_documents_async([neg_doc])

    service = CampaignService(rag_pipeline=rag)

    # 1. Проверяем генерацию с явным негативным ограничением, эмулирующим запрещенный хук
    user_data = {
        "company_name": "UCust AI",
        "niche": "B2B SaaS",
        "prompt": "Невероятный прорыв в сфере бизнеса только у нас",
        "tenant_id": "tenant_e2e_demo",
        "generate_image": False,
        "negative_constraints": [
            {
                "failed_hook": bad_hook_phrase,
                "penalty": 0.35,
                "reason": "Запрещено использовать клише 'Невероятный прорыв в сфере бизнеса только у нас'",
            }
        ]
    }

    state = PipelineState(
        session_id="e2e_sess_001",
        user_id="user_test",
        company_name="UCust AI",
        niche="B2B SaaS",
        topic="Невероятный прорыв в сфере бизнеса только у нас",
    )

    updated_state = await service.generate_campaign(state, user_data=user_data)

    print(f"Final PipelineState Critic Score: {updated_state.critic_score}")
    print(f"Final PipelineState Critic Flaws: {updated_state.critic_flaws}")
    print(f"Fact Check Passed: {updated_state.fact_check_passed}")

    assert updated_state.critic_score <= 0.50, f"Critic score ({updated_state.critic_score}) must be penalized to <= 0.50"
    assert updated_state.fact_check_passed is False, "fact_check_passed must be False due to negative constraint"
    assert any("Feedback Negative Constraint" in str(f) for f in updated_state.critic_flaws), "critic_flaws must capture negative constraint"

    print("✅ TEST 4 PASSED: CampaignService successfully detected negative constraint, penalized score, and rejected post.")


def run_all_tests():
    test_saiga_echo_chamber_guard()
    test_critic_munger_negative_constraint_penalization()
    test_celery_channel_batch_telemetry()
    asyncio.run(test_end_to_end_campaign_feedback_loop())
    print("\n" + "="*70)
    print("🎉 ALL 4 FEEDBACK LOOP INTEGRATION TESTS PASSED 100%!")
    print("="*70)


if __name__ == "__main__":
    run_all_tests()

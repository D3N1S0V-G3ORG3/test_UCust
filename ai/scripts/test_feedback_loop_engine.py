"""
File: ai/scripts/test_feedback_loop_engine.py
Модульный тест-сьют для проверки математического ядра и контрактов FeedbackLoopEngine:
1. Валидация Pydantic v2 схем PostTelemetryEvent, TelemetryMetrics, EngagementScore.
2. Расчет взвешенного ER (с повышенным весом репостов 1.2x и закладок 1.5x).
3. Расчет скользящей базовой линии тенанта (Mean, Median, StdDev) и Cold Start fallback.
4. Нормализация EngagementScore через Sigmoid(Z-Score), исключающая Self-Review Illusion.
5. Автоматическое выявление рискованных форматов (risky_formats) для тенанта.
6. Append-Only генерация директив для Clean RAG (proven_hooks и negative_constraints).
"""

import os
import sys
import asyncio
from typing import List

# Setup sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from schemas.feedback_state import (
    PerformanceTierEnum,
    TelemetryMetrics,
    GenerationMetadataLink,
    PostTelemetryEvent,
    EngagementScore,
    TenantBaseline,
    FeedbackKnowledgeRefinement,
)
from analytics.feedback_loop_engine import FeedbackLoopEngine


def test_contracts_and_deduplication():
    print("\n--- 1. Testing Feedback Contracts & Deduplication ---")
    event = PostTelemetryEvent(
        post_id="tg_post_1001",
        session_id="sess_gen_884",
        tenant_id="tenant_b2b",
        channel="@b2b_insights",
        platform="telegram",
        snapshot_window="24h",
        metrics=TelemetryMetrics(
            views=1000,
            likes=45,
            dislikes=2,
            comments_count=12,
            reposts=18,
            bookmarks=25,
            reactions_breakdown={"🔥": 20, "👍": 25, "👎": 2},
        ),
        generation_context=GenerationMetadataLink(
            session_id="sess_gen_884",
            post_id="tg_post_1001",
            tenant_id="tenant_b2b",
            channel="@b2b_insights",
            target_format="post",
            prompt_topic="B2B AI Automation",
            draft_snippet="Автоматизация рутины в B2B...",
            munger_triggers=["social_proof", "efficiency"],
        ),
    )

    assert event.deduplication_key == "tenant_b2b:telegram:tg_post_1001:24h"
    assert event.metrics.views == 1000
    assert event.metrics.reposts == 18
    print(f"   [OK] PostTelemetryEvent валидирован. Deduplication key: '{event.deduplication_key}'")


def test_raw_er_math_and_weights():
    print("\n--- 2. Testing Raw ER Formula & Weighted Interactions ---")
    metrics = TelemetryMetrics(
        views=1000,
        likes=50,             # 50 * 1.0 = 50
        dislikes=5,           # 5 * -2.0 = -10
        comments_count=10,    # 10 * 1.0 = 10
        reposts=20,           # 20 * 1.2 = 24
        bookmarks=30,         # 30 * 1.5 = 45
    )
    # Итого числитель: 50 + 24 + 45 + 10 - 10 = 119
    # ER% = (119 / 1000) * 100 = 11.9%
    er = FeedbackLoopEngine.calculate_raw_er(metrics)
    assert er == 11.9
    print(f"   [OK] Взвешенный расчет ER подтвержден: {er}%")

    nai = FeedbackLoopEngine.calculate_approval_index(likes=50, dislikes=5)
    # NAI = 50 / (50 + 5 + 1) = 50 / 56 ~ 0.8929
    assert 0.89 <= nai <= 0.90
    print(f"   [OK] Net Approval Index (NAI) подтвержден: {nai}")


def test_baseline_and_normalized_scoring():
    print("\n--- 3. Testing Tenant Baseline & Normalized Scoring (Z-Score + Sigmoid) ---")
    engine = FeedbackLoopEngine()
    tenant_id = "tenant_cafe"
    channel = "@cozy_coffee"

    # 3.1 Cold Start: выборка пуста, применяется дефолтный бейзлайн
    cold_baseline = engine.get_tenant_baseline(tenant_id, channel)
    assert cold_baseline.sample_size == 0
    assert cold_baseline.mean_er == 2.5
    print(f"   [OK] Cold Start Baseline: SampleSize={cold_baseline.sample_size}, Mean={cold_baseline.mean_er}%")

    # 3.2 Наполняем историю 6 постами со средним ER ~ 3.0% (std ~ 0.5)
    # Посты: 2.8%, 3.0%, 3.2%, 2.9%, 3.1%, 3.0%
    for i, er_val in enumerate([2.8, 3.0, 3.2, 2.9, 3.1, 3.0]):
        ev = PostTelemetryEvent(
            post_id=f"hist_{i}",
            session_id=f"sess_{i}",
            tenant_id=tenant_id,
            channel=channel,
            snapshot_window="24h",
            metrics=TelemetryMetrics(
                views=1000,
                likes=int(er_val * 10),  # примерно дает er_val %
            ),
        )
        engine.ingest_telemetry(ev)

    updated_baseline = engine.get_tenant_baseline(tenant_id, channel)
    assert updated_baseline.sample_size == 6
    assert 2.9 <= updated_baseline.mean_er <= 3.1
    print(f"   [OK] Обновленный Baseline (6 постов): Mean={updated_baseline.mean_er}%, Median={updated_baseline.median_er}%, StdDev={updated_baseline.std_dev_er}")

    # 3.3 Оценка среднего поста (ER = 3.0% ~ Mean): нормализованный скор должен быть около 0.50
    avg_score = engine.evaluate_score(raw_er=3.0, baseline=updated_baseline, likes=30, dislikes=0, views=1000)
    assert 0.45 <= avg_score.normalized_score <= 0.55
    assert avg_score.tier == PerformanceTierEnum.AVERAGE
    print(f"   [OK] Оценка среднего поста (3.0% vs {updated_baseline.mean_er}%): Score={avg_score.normalized_score} (Tier: {avg_score.tier.value})")

    # 3.4 Оценка выдающегося поста (ER = 6.0% >> Mean): нормализованный скор > 0.85 (STELLAR)
    stellar_score = engine.evaluate_score(raw_er=6.0, baseline=updated_baseline, likes=60, dislikes=0, views=1000)
    assert stellar_score.normalized_score >= 0.85
    assert stellar_score.tier == PerformanceTierEnum.STELLAR
    print(f"   [OK] Оценка выдающегося поста (6.0% vs {updated_baseline.mean_er}%): Score={stellar_score.normalized_score} (Tier: {stellar_score.tier.value})")

    # 3.5 Оценка провального поста (ER = 0.5% << Mean): нормализованный скор < 0.20 (CRITICAL_FAIL)
    fail_score = engine.evaluate_score(raw_er=0.5, baseline=updated_baseline, likes=5, dislikes=5, views=1000)
    assert fail_score.normalized_score <= 0.20
    assert fail_score.tier == PerformanceTierEnum.CRITICAL_FAIL
    print(f"   [OK] Оценка провального поста (0.5% vs {updated_baseline.mean_er}%): Score={fail_score.normalized_score} (Tier: {fail_score.tier.value})")


def test_risky_formats_detection():
    print("\n--- 4. Testing Risky Formats Pattern Detection ---")
    engine = FeedbackLoopEngine()
    tenant_id = "tenant_agency"
    channel = "@agency_live"

    # Добавляем 5 базовых хороших постов формата "post" (ER ~ 4.0%)
    for i in range(5):
        engine.ingest_telemetry(PostTelemetryEvent(
            post_id=f"base_{i}",
            session_id=f"sess_{i}",
            tenant_id=tenant_id,
            channel=channel,
            snapshot_window="24h",
            metrics=TelemetryMetrics(views=1000, likes=40),
            generation_context=GenerationMetadataLink(
                session_id=f"sess_{i}", post_id=f"base_{i}", tenant_id=tenant_id, channel=channel, target_format="post"
            ),
        ))

    # Добавляем 3 поста формата "storytelling" с крайне низким откликом (ER ~ 0.4%)
    for i in range(3):
        engine.ingest_telemetry(PostTelemetryEvent(
            post_id=f"story_{i}",
            session_id=f"sess_st_{i}",
            tenant_id=tenant_id,
            channel=channel,
            snapshot_window="24h",
            metrics=TelemetryMetrics(views=1000, likes=4),
            generation_context=GenerationMetadataLink(
                session_id=f"sess_st_{i}", post_id=f"story_{i}", tenant_id=tenant_id, channel=channel, target_format="storytelling"
            ),
        ))

    baseline = engine.get_tenant_baseline(tenant_id, channel)
    assert "storytelling" in baseline.risky_formats
    assert "post" not in baseline.risky_formats
    print(f"   [OK] Алгоритм выявил рискованный формат: {baseline.risky_formats}")
    print(f"        Статистика форматов: {baseline.format_stats}")


async def test_append_only_knowledge_refinement():
    print("\n--- 5. Testing Append-Only Knowledge Refinement (Clean RAG Integration) ---")
    engine = FeedbackLoopEngine()
    tenant_id = "tenant_saas"
    channel = "@saas_tech"

    # 1. Кейс: Успешный пост -> proven_hook
    success_event = PostTelemetryEvent(
        post_id="post_stellar_1",
        session_id="sess_top_1",
        tenant_id=tenant_id,
        channel=channel,
        snapshot_window="24h",
        metrics=TelemetryMetrics(views=1000, likes=80, reposts=25, bookmarks=30),
        generation_context=GenerationMetadataLink(
            session_id="sess_top_1",
            post_id="post_stellar_1",
            tenant_id=tenant_id,
            channel=channel,
            target_format="carousel",
            prompt_topic="Zero-Downtime Migration",
            draft_snippet="Как мигрировать 100 млн записей без секунды простоя...",
            munger_triggers=["inversion", "social_proof"],
        ),
    )
    score_success = engine.ingest_telemetry(success_event)
    refinement_success = engine.refine_knowledge(success_event, score_success)

    assert len(refinement_success.proven_hooks) == 1
    assert len(refinement_success.negative_constraints) == 0
    hook_data = refinement_success.proven_hooks[0]
    assert hook_data["type"] == "proven_hook"
    assert "Zero-Downtime" in hook_data["topic"]
    print(f"   [OK] Сформирован proven_hook: '{hook_data['hook_text'][:40]}...' (Score={hook_data['normalized_score']})")

    # 2. Кейс: Провальный пост -> negative_constraint
    fail_event = PostTelemetryEvent(
        post_id="post_fail_1",
        session_id="sess_low_1",
        tenant_id=tenant_id,
        channel=channel,
        snapshot_window="24h",
        metrics=TelemetryMetrics(views=1000, likes=1, dislikes=15),
        generation_context=GenerationMetadataLink(
            session_id="sess_low_1",
            post_id="post_fail_1",
            tenant_id=tenant_id,
            channel=channel,
            target_format="post",
            prompt_topic="Generic Promo",
            draft_snippet="Уникальное торговое предложение для каждого клиента...",
        ),
    )
    score_fail = engine.ingest_telemetry(fail_event)
    refinement_fail = engine.refine_knowledge(fail_event, score_fail)

    assert len(refinement_fail.negative_constraints) == 1
    neg_data = refinement_fail.negative_constraints[0]
    assert neg_data["type"] == "negative_constraint"
    assert neg_data["critic_penalty"] == 0.40
    print(f"   [OK] Сформирован negative_constraint: '{neg_data['failed_hook'][:40]}...' (Penalty={neg_data['critic_penalty']})")

    # 3. Синхронизация с Clean RAG
    class MockRAGPipeline:
        def __init__(self):
            self.indexed_docs = []

        async def ingest_documents_async(self, docs):
            self.indexed_docs.extend(docs)
            return len(docs)

    mock_rag = MockRAGPipeline()
    c1 = await engine.sync_refinements_to_rag(refinement_success, mock_rag)
    c2 = await engine.sync_refinements_to_rag(refinement_fail, mock_rag)

    assert c1 == 1
    assert c2 == 1
    assert len(mock_rag.indexed_docs) == 2
    types = [d.metadata.get("type") for d in mock_rag.indexed_docs]
    assert "proven_hook" in types
    assert "negative_constraint" in types
    print(f"   [OK] Clean RAG индексация: проиндексировано {len(mock_rag.indexed_docs)} документов с метаданными {types}")


def main():
    print("=" * 70)
    print("🚀 RUNNING FEEDBACK LOOP ENGINE & BASELINE MATHEMATICS TEST SUITE")
    print("=" * 70)

    test_contracts_and_deduplication()
    test_raw_er_math_and_weights()
    test_baseline_and_normalized_scoring()
    test_risky_formats_detection()
    asyncio.run(test_append_only_knowledge_refinement())

    print("\n" + "=" * 70)
    print("🎉 ALL FEEDBACK LOOP ENGINE TESTS PASSED WITH 100% SUCCESS!")
    print("=" * 70)


if __name__ == "__main__":
    main()

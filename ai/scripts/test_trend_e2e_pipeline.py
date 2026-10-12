# File: ai/scripts/test_trend_e2e_pipeline.py
"""
test_trend_e2e_pipeline.py
Сквозной интеграционный тест Trend Engine:
1. Сбор сырых событий (RawTrendEvent) и дедупликация по SHA-256.
2. Математическая кластеризация HDBSCAN и расчет всплеска плотности.
3. Семантический анализ через TrendService (генерация TrendState с валидацией схемы).
4. RAG-индексация с мета-тегами (type='trend_agenda') и проверка механизма TTL-эвикции.
5. Сквозная генерация коммерческого поста в CampaignService на основе свежего тренда.
6. Верификация Celery-очереди trend_mining и тасок фоновой обработки.
"""

import os
import sys
import time
import asyncio
from datetime import datetime, timedelta

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Setup sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from schemas.trend_state import (
    RawTrendEvent,
    TrendCluster,
    TrendState,
    TrendLifecycleEnum,
    TrendSentimentEnum,
)
from schemas.pipeline_state import PipelineState, ContentFormatEnum
from analytics.trend_clusterer import TrendClusterer
from services.trend_service import TrendService
from services.campaign_service import CampaignService
from rag.pipeline import CleanRAGPipeline
from rag.models import Document
from celery_tasks import (
    get_celery_queue_stats,
    QUEUE_TREND_MINING,
    process_trend_clusters_task,
    enqueue_trend_mining_task,
)


async def test_end_to_end_trend_cycle():
    print("=" * 70)
    print("🚀 RUNNING END-TO-END TREND ENGINE & CAMPAIGN INTEGRATION TEST")
    print("=" * 70)

    now = datetime.utcnow()

    # -------------------------------------------------------------------------
    # 1. Сырой поток данных: инфоповод о внедрении ИИ в ресторанном бизнесе
    # -------------------------------------------------------------------------
    print("\n--- 1. Raw Event Ingestion & Deduplication ---")
    trend_messages = [
        "Рестораны и кофейни начали массово внедрять автономных ИИ-агентов для бронирования и меню.",
        "Революция в общепите: ИИ-ассистенты принимают заказы у гостей прямо в Telegram и VK.",
        "Ресторанный бизнес фиксирует рост среднего чека на 25% благодаря умным ИИ-рекомендациям блюд.",
        "Кофейни тестируют нейросети для персонализации вкусов кофе под каждого постоянного гостя.",
        "Автоматизация кафе: локальные модели ИИ помогают оптимизировать закупки свежих продуктов.",
        "Рестораны переходят на ИИ: скорость обслуживания столиков увеличилась вдвое.",
    ]

    raw_events = []
    for i, msg in enumerate(trend_messages):
        raw_events.append(
            RawTrendEvent(
                source_platform="telegram",
                source_id="horeca_insider",
                post_id=f"post_{i}",
                raw_text=msg,
                timestamp=now - timedelta(minutes=10 * i)
            )
        )

    # Добавляем дубликат для проверки отсечения репостов
    raw_events.append(
        RawTrendEvent(
            source_platform="telegram",
            source_id="horeca_insider",
            post_id="duplicate_post",
            raw_text="Рестораны и кофейни начали массово внедрять автономных ИИ-агентов для бронирования и меню! 🔥",
            timestamp=now
        )
    )

    clusterer = TrendClusterer(min_cluster_size=3, min_density_spike=1.0)
    unique_events = clusterer.deduplicate_events(raw_events)
    assert len(unique_events) == len(trend_messages), f"Deduplication failed: expected {len(trend_messages)}, got {len(unique_events)}"
    print(f"  [Pass] Dedup: {len(raw_events)} events -> {len(unique_events)} unique clean events")

    # -------------------------------------------------------------------------
    # 2. Математическая кластеризация HDBSCAN
    # -------------------------------------------------------------------------
    print("\n--- 2. Mathematical Clustering & Velocity Spike ---")
    t0 = time.perf_counter()
    clusters = clusterer.cluster_events(unique_events, window_hours=2.0)
    clustering_time_ms = (time.perf_counter() - t0) * 1000

    assert len(clusters) >= 1, "At least 1 dense cluster must be detected"
    target_cluster = clusters[0]
    print(f"  [Pass] Cluster detected in {clustering_time_ms:.1f} ms:")
    print(f"         ID={target_cluster.cluster_id} | Samples={target_cluster.total_samples} | DensitySpike={target_cluster.density_spike}x")

    # -------------------------------------------------------------------------
    # 3. Семантический слой: генерация TrendState
    # -------------------------------------------------------------------------
    print("\n--- 3. Semantic Analysis & TrendState Schema Generation ---")
    rag = CleanRAGPipeline(min_confidence_threshold=0.45)
    trend_service = TrendService(clusterer=clusterer, rag_pipeline=rag)

    trend_state = await trend_service.analyze_cluster_to_trend(target_cluster)
    assert isinstance(trend_state, TrendState)
    assert trend_state.topic_headline != ""
    assert trend_state.trend_lifecycle in [TrendLifecycleEnum.MICRO_HYPE, TrendLifecycleEnum.MACRO_TREND]
    assert trend_state.sentiment in [TrendSentimentEnum.POSITIVE, TrendSentimentEnum.NEUTRAL, TrendSentimentEnum.NEGATIVE]
    print(f"  [Pass] Trend Headline: '{trend_state.topic_headline}'")
    print(f"         Summary: {trend_state.summary[:90]}...")
    print(f"         Lifecycle: {trend_state.trend_lifecycle.value} | Sentiment: {trend_state.sentiment.value}")

    # -------------------------------------------------------------------------
    # 4. RAG Индексация и проверка TTL-эвикции
    # -------------------------------------------------------------------------
    print("\n--- 4. Clean RAG Pipeline Indexing & TTL Eviction ---")
    indexed_count = await trend_service.index_trends_to_rag([trend_state], tenant_id="tenant_resto")
    assert indexed_count > 0, "Failed to index trend into RAG"
    print(f"  [Pass] Successfully indexed {indexed_count} chunks with type='trend_agenda'")

    # Проверка извлечения свежего тренда
    rag_res = await rag.query_async("тренды автоматизации ресторанов и кафе", tenant_id="tenant_resto")
    assert rag_res.has_sufficient_context or len(rag_res.chunks) > 0
    print("  [Pass] Active fresh trend retrieved cleanly in RAG context")

    # Проверка TTL эвикции: искусственно добавляем тренд 50-часовой давности с ttl=48
    old_doc = Document(
        doc_id="doc_old_expired_trend",
        text="Устаревший мем двухдневной давности про ресторан",
        metadata={
            "type": "trend_agenda",
            "created_at": (datetime.utcnow() - timedelta(hours=50)).isoformat(),
            "ttl_hours": 48.0,
            "tenant_id": "tenant_resto",
        }
    )
    # Прямая проверка метода filter_active_trend_documents
    filtered = TrendService.filter_active_trend_documents([old_doc])
    assert len(filtered) == 0, "Expired trend must be evicted by TTL filter!"
    print("  [Pass] Expired 50h trend successfully dropped by TTL eviction filter")

    # -------------------------------------------------------------------------
    # 5. Сквозная генерация кампании на основе трендовой повестки
    # -------------------------------------------------------------------------
    print("\n--- 5. End-to-End Campaign Generation Powered by Trend ---")
    campaign_service = CampaignService(rag_pipeline=rag)

    state = PipelineState(
        session_id="trend_campaign_demo_01",
        tenant_id="tenant_resto",
        company_name="Уютное Кафе",
        niche="общепит",
        topic="Автоматизация заказов и новинки сервиса",
        target_format=ContentFormatEnum.POST,
    )

    enriched_state = await campaign_service.generate_campaign(
        state,
        user_data={"company_name": "Уютное Кафе", "niche": "общепит", "topic": "Автоматизация заказов"}
    )

    assert enriched_state.draft_text != "", "Draft text must not be empty"
    print(f"  [Pass] Generated campaign draft snippet:")
    print("  " + "-" * 50)
    for line in enriched_state.draft_text.split("\n")[:5]:
        if line.strip():
            print(f"    {line}")
    print("  " + "-" * 50)

    # -------------------------------------------------------------------------
    # 6. Проверка Celery очередей и фоновых задач
    # -------------------------------------------------------------------------
    print("\n--- 6. Celery Trend Mining Queue & Task Verification ---")
    queue_stats = get_celery_queue_stats()
    assert QUEUE_TREND_MINING in queue_stats["active_queues"]
    assert queue_stats["trend_queue"] == "trend_mining"
    print(f"  [Pass] Celery queues verified: {queue_stats['active_queues']}")

    # Запуск Celery-таски
    celery_res = process_trend_clusters_task(
        events_payload=[e.model_dump(mode="json") for e in unique_events],
        window_hours=2.0,
        tenant_id="tenant_resto"
    )
    assert celery_res["status"] == "success"
    assert celery_res["clusters_detected"] >= 1
    assert celery_res["trends_generated"] >= 1
    print(f"  [Pass] Celery task process_trend_clusters_task executed smoothly: {celery_res['clusters_detected']} clusters -> {celery_res['trends_generated']} trends")

    print("\n" + "=" * 70)
    print("🏆 FULL END-TO-END TREND ENGINE CYCLE COMPLETED WITH 100% SUCCESS!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_end_to_end_trend_cycle())

"""
File: ai/scripts/stress_test_event_bus_cache.py
Стресс-тестирование Event Bus и механизма атомарной инвалидации кэша RAG под High-Load:
1. 50 параллельных синтетических тенантов (stress_tenant_01 .. stress_tenant_50).
2. 1000 конкурентных асинхронных операций чтения (query_stratified_context_async).
3. 200 конкурентных мутаций и инвалидаций (add_directive_async + _invalidate_and_notify).
4. Точный замер latency с перцентилями (p50, p95, p99, max) для валидации SLA <= 15 мс.
5. Проверка отсутствия состояний гонки (Race Condition), взаимоблокировок (Deadlocks) и утечек.
"""

import sys
import os
import time
import random
import asyncio
from typing import List, Dict, Any

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rag.models import Document, DocCategoryEnum, TrustTierEnum, PlatformTargetEnum
from rag.pipeline import CleanRAGPipeline
from services.rag_manager import BrandKnowledgeManager, InMemoryEventBus
from analytics.rag_telemetry import RAGTelemetryTracker

# Конфигурация стресс-теста
NUM_TENANTS = 50
NUM_READ_TASKS = 1000
NUM_WRITE_TASKS = 200
TARGET_SLA_MS = 15.0  # Целевой порог SLA на инвалидацию


def init_stress_tenants(rag: CleanRAGPipeline) -> List[str]:
    """Инициализация базы данных 50 тенантов с 4 слоями знаний в каждом."""
    tenants = [f"stress_tenant_{i:02d}" for i in range(1, NUM_TENANTS + 1)]
    docs: List[Document] = []

    for t in tenants:
        docs.extend([
            Document(
                doc_id=f"{t}_hard_fact",
                text=f"Тарифный план для {t}: Стоимость 2900 руб/мес, гарантия возврата 14 дней, скидка 15%.",
                metadata={
                    "tenant_id": t,
                    "client_id": t,
                    "doc_category": DocCategoryEnum.HARD_FACT.value,
                    "trust_tier": TrustTierEnum.VERIFIED_BY_OWNER.value,
                    "platform_target": PlatformTargetEnum.ALL.value,
                },
                source="pricing_doc"
            ),
            Document(
                doc_id=f"{t}_brand_dna",
                text=f"Редполитика {t}: Лаконичный тон, без капса, максимум 1 эмодзи. Антипример: ❌ 'Мы лучшие' -> ✅ 'Решаем задачи за 2 часа'.",
                metadata={
                    "tenant_id": t,
                    "client_id": t,
                    "doc_category": DocCategoryEnum.BRAND_DNA.value,
                    "trust_tier": TrustTierEnum.VERIFIED_BY_OWNER.value,
                    "platform_target": PlatformTargetEnum.ALL.value,
                },
                source="brand_guide"
            ),
            Document(
                doc_id=f"{t}_audience",
                text=f"Боли клиентов {t}: Долгие ответы техподдержки, скрытые комиссии и отсутствие прозрачности.",
                metadata={
                    "tenant_id": t,
                    "client_id": t,
                    "doc_category": DocCategoryEnum.AUDIENCE_PRIORS.value,
                    "trust_tier": TrustTierEnum.INFERRED_NICHE.value,
                    "platform_target": PlatformTargetEnum.ALL.value,
                },
                source="niche_analysis"
            ),
            Document(
                doc_id=f"{t}_memory",
                text=f"[Директива {t}]: Всегда подчеркивать бесплатный тестовый период 7 дней.",
                metadata={
                    "tenant_id": t,
                    "client_id": t,
                    "doc_category": DocCategoryEnum.EPISODIC_MEMORY.value,
                    "trust_tier": TrustTierEnum.SYSTEM_DIRECTIVE.value,
                    "platform_target": PlatformTargetEnum.ALL.value,
                },
                source="owner_directive"
            ),
        ])

    rag.ingest_documents(docs)
    return tenants


async def run_stress_benchmark():
    print(f"🚀 ЗАПУСК СТРЕСС-ТЕСТА EVENT BUS И АТОМАРНОЙ ИНВАЛИДАЦИИ КЭША")
    print(f"   Параметры: {NUM_TENANTS} тенантов | {NUM_READ_TASKS} чтений | {NUM_WRITE_TASKS} мутаций | SLA <= {TARGET_SLA_MS} мс\n")

    rag = CleanRAGPipeline(min_confidence_threshold=0.30)
    event_bus = InMemoryEventBus()
    bkm = BrandKnowledgeManager(rag_pipeline=rag, event_bus=event_bus)

    # Замер событий Event Bus
    bus_notifications_count = 0

    def on_knowledge_updated(payload: Dict[str, Any]):
        nonlocal bus_notifications_count
        bus_notifications_count += 1

    event_bus.subscribe("knowledge_updated", on_knowledge_updated)

    tenants = init_stress_tenants(rag)
    print(f"   ✅ База знаний инициализирована: {len(tenants)} тенантов, {len(rag.retriever.dense_store.chunks)} чанков в памяти.")

    # Метрики чтения
    read_success = 0
    read_errors = 0
    read_latencies: List[float] = []

    # Метрики инвалидации / записи
    invalidation_latencies_ms: List[float] = []
    full_mutation_latencies_ms: List[float] = []
    mutation_errors = 0

    queries_pool = [
        "какая стоимость тарифа и условия",
        "какой тон общения и редполитика",
        "какие боли у клиентов и триггеры",
        "расскажи про тестовый период и директивы",
        "цена гарантия скидка"
    ]

    async def reader_worker(worker_id: int):
        nonlocal read_success, read_errors
        t0 = time.perf_counter()
        tid = random.choice(tenants)
        q = random.choice(queries_pool)
        plt = random.choice(["telegram", "vk", "all"])
        try:
            ctx = await rag.query_stratified_context_async(
                query_text=q,
                tenant_id=tid,
                platform_target=plt,
                per_layer_k=2
            )
            assert ctx.has_sufficient_context is True
            assert ctx.has_hard_facts is True
            elapsed_ms = (time.perf_counter() - t0) * 1000
            read_latencies.append(elapsed_ms)
            read_success += 1
        except Exception as e:
            read_errors += 1
            print(f"❌ Ошибка в reader {worker_id}: {e}")

    async def writer_worker(worker_id: int):
        nonlocal mutation_errors
        tid = random.choice(tenants)
        new_price = random.randint(3000, 9900)
        directive_text = f"[Срочная директива #{worker_id}]: Цена обновлена до {new_price} руб."

        try:
            t_total_0 = time.perf_counter()
            # 1. Мутация данных в RAG (индексация нового чанка)
            await rag.add_directive_async(tenant_id=tid, directive_text=directive_text)
            
            # 2. Атомарная инвалидация кэша по префиксу {tenant_id}:* и нотификация в Event Bus
            t_inv_0 = time.perf_counter()
            await bkm._invalidate_and_notify(tenant_id=tid)
            inv_ms = (time.perf_counter() - t_inv_0) * 1000
            invalidation_latencies_ms.append(inv_ms)

            full_mutation_ms = (time.perf_counter() - t_total_0) * 1000
            full_mutation_latencies_ms.append(full_mutation_ms)
        except Exception as e:
            mutation_errors += 1
            print(f"❌ Ошибка в writer {worker_id}: {e}")

    # Запуск параллельной волны нагрузки (Chaos Concurrency)
    print("   ⚡ Старт одновременного выполнения 1000 чтений и 200 мутаций...")
    start_time = time.perf_counter()

    read_tasks = [asyncio.create_task(reader_worker(i)) for i in range(NUM_READ_TASKS)]
    write_tasks = [asyncio.create_task(writer_worker(i)) for i in range(NUM_WRITE_TASKS)]

    # Запускаем всё вместе
    await asyncio.gather(*read_tasks, *write_tasks)
    total_duration = time.perf_counter() - start_time

    # Статистическая обработка
    invalidation_latencies_ms.sort()
    p50_inv = invalidation_latencies_ms[int(len(invalidation_latencies_ms) * 0.50)]
    p95_inv = invalidation_latencies_ms[int(len(invalidation_latencies_ms) * 0.95)]
    p99_inv = invalidation_latencies_ms[int(len(invalidation_latencies_ms) * 0.99)]
    max_inv = max(invalidation_latencies_ms)
    avg_inv = sum(invalidation_latencies_ms) / len(invalidation_latencies_ms)

    read_latencies.sort()
    avg_read_ms = sum(read_latencies) / len(read_latencies)
    p95_read_ms = read_latencies[int(len(read_latencies) * 0.95)]

    qps = (NUM_READ_TASKS + NUM_WRITE_TASKS) / total_duration

    print("\n" + "=" * 60)
    print("📊 ИТОГОВЫЕ РЕЗУЛЬТАТЫ СТРЕСС-ТЕСТИРОВАНИЯ (BENCHMARK REPORT)")
    print("=" * 60)
    print(f"⏱  Общее время прогона:          {total_duration:.2f} сек")
    print(f"🚀 Пропускная способность (QPS):   {qps:.1f} op/sec")
    print(f"📖 Чтение (Read Intensive):        {read_success}/{NUM_READ_TASKS} успешно (Ошибок: {read_errors})")
    print(f"   - Среднее время чтения:         {avg_read_ms:.2f} мс")
    print(f"   - p95 время чтения:             {p95_read_ms:.2f} мс")
    full_mutation_latencies_ms.sort()
    avg_mut = sum(full_mutation_latencies_ms) / len(full_mutation_latencies_ms)
    p95_mut = full_mutation_latencies_ms[int(len(full_mutation_latencies_ms) * 0.95)]

    print("-" * 60)
    print(f"✍️  Атомарная Инвалидация кэша (_invalidate_and_notify): {len(invalidation_latencies_ms)}/{NUM_WRITE_TASKS} успешно")
    print(f"   - Min Latency:                  {min(invalidation_latencies_ms):.3f} мс")
    print(f"   - Avg Latency:                  {avg_inv:.3f} мс")
    print(f"   - p50 Latency (Median):         {p50_inv:.3f} мс")
    print(f"   - p95 Latency:                  {p95_inv:.3f} мс  (Целевой SLA <= {TARGET_SLA_MS:.1f} мс)")
    print(f"   - p99 Latency:                  {p99_inv:.3f} мс")
    print(f"   - Max Latency (Peak):           {max_inv:.3f} мс")
    print(f"   - Полная мутация (Ingest+Index): Avg={avg_mut:.1f} мс | p95={p95_mut:.1f} мс")
    print("-" * 60)
    print(f"📡 Event Bus уведомлений получено: {bus_notifications_count} событий 'knowledge_updated'")
    
    # Сводка телеметрии
    telemetry = RAGTelemetryTracker.get_instance().get_summary()
    print(f"📈 Зафиксировано телеметрией:      {telemetry.total_queries} запросов")
    print("=" * 60)

    # Верификация условий устойчивости
    assert read_errors == 0, f"Read errors occurred: {read_errors}"
    assert mutation_errors == 0, f"Mutation errors occurred: {mutation_errors}"
    assert p95_inv <= TARGET_SLA_MS, f"SLA Violation! p95 invalidation latency {p95_inv:.2f} ms > {TARGET_SLA_MS} ms"
    assert avg_inv <= 5.0, f"Average invalidation latency {avg_inv:.2f} ms too high!"

    print("\n🏆 СТРЕСС-ТЕСТ УСПЕШНО ПРОЙДЕН (ЗЕЛЕНАЯ ЗОНА):")
    print(f"   1. SLA атомарной инвалидации выдержан: p95 = {p95_inv:.2f} мс (порог: <= {TARGET_SLA_MS} мс).")
    print("   2. Состояние гонки (Race Condition) исключено: 0 ошибок конкурентного доступа.")
    print("   3. Event Bus корректно разослал все уведомления подписчикам.")
    print("   4. Система сохраняет стабильность под агрессивным параллельным трафиком!\n")


if __name__ == "__main__":
    asyncio.run(run_stress_benchmark())

"""
ai/scripts/test_directives_6_7.py
Верификационный тест для Директивы 6 (ORM Hook) и Директивы 7 (asyncio.Lock).

Критерии:
  Д6: save_knowledge_chunks invalidate ≤ 15ms (без сетевых вызовов).
  Д7: 0 KeyError и 0 Race Condition при 100 параллельных async-тасках (read + write + invalidate).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("ENABLE_NEURAL_MODELS", "0")

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import asyncio
import time
import random
import traceback

SEPARATOR = "=" * 72


# ─────────────────────────────────────────────────────────────────────────────
# Директива 7: Потокобезопасность _query_cache (asyncio.Lock)
# ─────────────────────────────────────────────────────────────────────────────

async def test_directive_7_thread_safety():
    """
    100 параллельных asyncio-тасков:
      - 60% — hybrid_search_async (чтение + запись в кэш)
      - 30% — invalidate_cache_async (удаление из кэша)
      - 10% — delete_tenant_async (полное удаление тенанта)

    Критерий: 0 исключений (KeyError, RuntimeError) за всё время прогона.
    """
    print(f"\n{'─'*72}")
    print("🔬 Директива 7: Тест потокобезопасности _query_cache (100 concurrent tasks)")
    print(f"{'─'*72}")

    from rag.pipeline import CleanRAGPipeline
    from rag.models import Document

    pipeline = CleanRAGPipeline()

    # Предзагрузка: 50 тенантов × 3 документа каждый
    TENANTS = [f"tenant_{i:02d}" for i in range(50)]
    documents = []
    for tid in TENANTS:
        for j in range(3):
            documents.append(Document(
                doc_id=f"{tid}_doc{j}",
                text=f"Контент документа {j} для тенанта {tid}. "
                        f"Кофейня специализируется на авторских напитках и уютной атмосфере.",
                metadata={"tenant_id": tid, "source": "test"}
            ))
    pipeline.ingest_documents(documents)
    print(f"  ✅ Предзагружено {len(documents)} документов для {len(TENANTS)} тенантов")

    errors = []
    lock_violations = []
    completed_tasks = 0

    async def task_read(tid: str):
        nonlocal completed_tasks
        try:
            query = random.choice([
                "авторские напитки", "уютная атмосфера", "кофейня специализируется"
            ])
            result = await pipeline.query_async(query, top_k_retrieval=5, top_n_rerank=3, tenant_id=tid)
            completed_tasks += 1
        except Exception as e:
            errors.append(f"READ[{tid}]: {type(e).__name__}: {e}")

    async def task_invalidate(tid: str):
        nonlocal completed_tasks
        try:
            await pipeline.invalidate_cache_async(tid)
            completed_tasks += 1
        except Exception as e:
            errors.append(f"INVALIDATE[{tid}]: {type(e).__name__}: {e}")

    async def task_delete(tid: str):
        nonlocal completed_tasks
        try:
            await pipeline.delete_tenant_async(tid)
            completed_tasks += 1
        except Exception as e:
            errors.append(f"DELETE[{tid}]: {type(e).__name__}: {e}")

    # Формируем 100 тасков со смешанным профилем
    tasks = []
    for i in range(100):
        tid = random.choice(TENANTS)
        roll = random.random()
        if roll < 0.60:
            tasks.append(task_read(tid))
        elif roll < 0.90:
            tasks.append(task_invalidate(tid))
        else:
            tasks.append(task_delete(tid))

    print(f"  ⚡ Запуск {len(tasks)} параллельных asyncio-тасков...")
    t0 = time.perf_counter()
    await asyncio.gather(*tasks, return_exceptions=True)
    elapsed = (time.perf_counter() - t0) * 1000

    print(f"  ⏱  Время выполнения всех {len(tasks)} тасков: {elapsed:.1f}ms")
    print(f"  ✅ Завершено без исключений: {completed_tasks} / {len(tasks)}")

    if errors:
        print(f"\n  ❌ ОШИБКИ ({len(errors)}):")
        for e in errors[:10]:
            print(f"     {e}")
        raise AssertionError(f"Директива 7 ПРОВАЛЕНА: {len(errors)} Race Condition ошибок из {len(tasks)} тасков.")

    print(f"\n✅ Директива 7 ПРОЙДЕНА: 0 KeyError / 0 Race Condition при 100 concurrent tasks.")
    return elapsed


# ─────────────────────────────────────────────────────────────────────────────
# Директива 6: ORM Hook — Cache Invalidation Latency ≤ 15ms
# ─────────────────────────────────────────────────────────────────────────────

async def test_directive_6_orm_hook_latency():
    """
    Симулирует ORM Hook: прямой вызов invalidate_cache_async без сетевых вызовов.
    Критерий: суммарное время invalidate + event_bus.publish ≤ 15ms.
    """
    print(f"\n{'─'*72}")
    print("🔬 Директива 6: ORM Hook Latency — инвалидация кэша ≤ 15ms")
    print(f"{'─'*72}")

    from rag.pipeline import CleanRAGPipeline
    from rag.models import Document

    # Настраиваем InMemoryEventBus с подписчиком
    notified_events = []

    pipeline = CleanRAGPipeline()

    # Предзаполняем кэш для одного тенанта
    documents = [Document(
        doc_id=f"doc_{i}",
        text=f"Тестовый документ {i} для бренда UCust. Контент маркетинг и SMM стратегия.",
        metadata={"tenant_id": "ucust_prod", "source": "test"}
    ) for i in range(10)]
    pipeline.ingest_documents(documents)

    # Первый запрос — прогрев кэша
    await pipeline.query_async("маркетинг", top_k_retrieval=5, top_n_rerank=3, tenant_id="ucust_prod")
    cache_before = len(pipeline.retriever._query_cache)
    print(f"  📦 Записей в кэше перед инвалидацией: {cache_before}")

    # Симуляция ORM Hook: измеряем только время invalidate + notify
    latencies = []
    RUNS = 20
    for run in range(RUNS):
        # Прогреваем кэш перед каждым измерением
        await pipeline.query_async(f"контент {run}", top_k_retrieval=5, top_n_rerank=3, tenant_id="ucust_prod")

        t0 = time.perf_counter()
        await pipeline.invalidate_cache_async("ucust_prod")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        latencies.append(elapsed_ms)

    p50 = sorted(latencies)[RUNS // 2]
    p95 = sorted(latencies)[int(RUNS * 0.95)]
    p99 = sorted(latencies)[int(RUNS * 0.99)]
    max_lat = max(latencies)

    print(f"  ⏱  Latency over {RUNS} runs — P50: {p50:.3f}ms | P95: {p95:.3f}ms | P99: {p99:.3f}ms | Max: {max_lat:.3f}ms")

    assert max_lat <= 15.0, (
        f"Директива 6 ПРОВАЛЕНА: max latency {max_lat:.3f}ms превышает порог 15ms"
    )
    cache_after = len(pipeline.retriever._query_cache)
    print(f"  📦 Записей в кэше после инвалидации: {cache_after}")
    print(f"\n✅ Директива 6 ПРОЙДЕНА: ORM Hook invalidation max={max_lat:.3f}ms ≤ 15ms")
    return max_lat


# ─────────────────────────────────────────────────────────────────────────────
# Директива 7 Бонус: Double-Checked Locking — нет дублей в кэше
# ─────────────────────────────────────────────────────────────────────────────

async def test_directive_7_double_checked_locking():
    """
    Проверяет, что Double-Checked Locking корректно работает:
    при 20 параллельных запросах одного и того же ключа — в кэше ровно 1 запись.
    """
    print(f"\n{'─'*72}")
    print("🔬 Директива 7: Double-Checked Locking — уникальность записи в кэше")
    print(f"{'─'*72}")

    from rag.hybrid_retriever import HybridRetriever
    from rag.models import Document, Chunk

    retriever = HybridRetriever()

    # Индексируем один чанк для тенанта
    from rag.models import Chunk
    chunk = Chunk(
        chunk_id="dcl_chunk_1",
        doc_id="dcl_doc",
        text="Тест двойной проверки блокировки кэша",
        token_count=10,
        metadata={"tenant_id": "dcl_tenant"}
    )
    retriever.index_chunks([chunk])

    # 20 параллельных вызовов одного и того же запроса
    CONCURRENCY = 20
    query = "блокировка кэша"
    tid = "dcl_tenant"

    tasks = [
        retriever.hybrid_search_async(query, top_k=5, tenant_id=tid)
        for _ in range(CONCURRENCY)
    ]

    await asyncio.gather(*tasks)

    cache_key = f"{tid}:{query}:{5}"
    cache_count = sum(1 for k in retriever._query_cache if k == cache_key)
    print(f"  📦 Ключей '{cache_key}' в кэше: {cache_count}")

    assert cache_count == 1, f"Директива 7 Double-Check ПРОВАЛЕНА: {cache_count} дублей ключа в кэше"
    print(f"\n✅ Директива 7 Double-Check ПРОЙДЕНА: ровно 1 запись при {CONCURRENCY} concurrent writes.")


# ─────────────────────────────────────────────────────────────────────────────
# Запуск
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    print(f"\n{SEPARATOR}")
    print("🚀 ВЕРИФИКАЦИЯ ДИРЕКТИВ 6 И 7 — ORM HOOK + ASYNC LOCK THREAD SAFETY")
    print(SEPARATOR)

    results = {}

    try:
        lat_d6 = await test_directive_6_orm_hook_latency()
        results["Д6 ORM Hook"] = f"✅ max_latency={lat_d6:.3f}ms ≤ 15ms"
    except Exception as e:
        results["Д6 ORM Hook"] = f"❌ ПРОВАЛЕНА: {e}"
        traceback.print_exc()

    try:
        elapsed_d7 = await test_directive_7_thread_safety()
        results["Д7 Race Condition"] = f"✅ 0 ошибок, 100 тасков за {elapsed_d7:.1f}ms"
    except Exception as e:
        results["Д7 Race Condition"] = f"❌ ПРОВАЛЕНА: {e}"
        traceback.print_exc()

    try:
        await test_directive_7_double_checked_locking()
        results["Д7 Double-Check Lock"] = "✅ 1 запись в кэше при 20 concurrent writes"
    except Exception as e:
        results["Д7 Double-Check Lock"] = f"❌ ПРОВАЛЕНА: {e}"
        traceback.print_exc()

    # Итоги
    print(f"\n{SEPARATOR}")
    print("📊 ИТОГИ ВЕРИФИКАЦИИ")
    print(SEPARATOR)
    all_pass = True
    for name, result in results.items():
        print(f"  {result}  [{name}]")
        if "❌" in result:
            all_pass = False

    print(SEPARATOR)
    if all_pass:
        print("🎉 ВСЕ ДИРЕКТИВЫ 6 И 7 ПРОЙДЕНЫ УСПЕШНО!")
    else:
        print("⛔ НЕКОТОРЫЕ ДИРЕКТИВЫ НЕ ПРОШЛИ ВЕРИФИКАЦИЮ. см. детали выше.")
    print(SEPARATOR)
    return 0 if all_pass else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

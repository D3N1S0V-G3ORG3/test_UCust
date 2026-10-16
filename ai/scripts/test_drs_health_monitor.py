"""
File: ai/scripts/test_drs_health_monitor.py
Интеграционный тест фонового сервиса DRS Health Monitor и Celery-воркера:
1. Low DRS Trigger: обнаружение тенанта с DRS < 40 и запуск опроса по первому слоту.
2. High Fallback Trigger: обнаружение тенанта с Fallback Rate >= 50%.
3. Healthy Skip: пропуск здоровых тенантов с DRS >= 75.
4. Anti-Spam / Cooldown: предотвращение повторных сообщений в течение 24 часов.
5. Loop Closure: проверка связи между DRSHealthMonitor -> Telegram -> SlotElevationHandler.
6. Celery Task Execution: вызов monitor_drs_and_trigger_interrogation_task.
"""

import sys
import os
import asyncio
from typing import Dict, Any

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from analytics.rag_telemetry import RAGTelemetryTracker
from analytics.drs_health_monitor import DRSHealthMonitor, TenantHealthStatus
from skills.slot_elevation_handler import SlotElevationHandler
from rag.models import RAGContext, Chunk, DocCategoryEnum
from rag.pipeline import CleanRAGPipeline
from services.rag_manager import BrandKnowledgeManager
from celery_tasks import monitor_drs_and_trigger_interrogation_task


async def test_drs_health_monitor_lifecycle():
    print("🚀 СТАРТ ТЕСТИРОВАНИЯ DRS HEALTH MONITOR & INTERROGATION TRIGGER\n")

    # 1. Инициализация контура RAG, Telemetry и Handler
    rag = CleanRAGPipeline(min_confidence_threshold=0.30)
    bkm = BrandKnowledgeManager(rag_pipeline=rag)
    elevation_handler = SlotElevationHandler(rag_pipeline=rag, rag_manager=bkm)
    telemetry = RAGTelemetryTracker(buffer_size=100)

    monitor = DRSHealthMonitor(
        elevation_handler=elevation_handler,
        telemetry_tracker=telemetry,
        min_drs_threshold=40,
        max_fallback_rate_pct=50.0,
        min_queries_for_fallback=2,
        cooldown_seconds=86400
    )

    tenant_red = "barbershop_boroda"     # DRS = 25 (Красная зона, нет цен)
    tenant_fallback = "craft_pizza"       # DRS = 45, но Fallback Rate = 66%
    tenant_green = "tech_corp_vip"        # DRS = 90 (Зеленая зона, полная фактура)

    user_red = "tg_owner_101"
    user_fallback = "tg_owner_202"
    user_green = "tg_owner_303"

    monitor.register_tenant_telegram(tenant_red, user_red)
    monitor.register_tenant_telegram(tenant_fallback, user_fallback)
    monitor.register_tenant_telegram(tenant_green, user_green)

    # Задаем досье с недостающими слотами
    monitor.register_tenant_dossier(tenant_red, {
        "data_richness_score": 25,
        "missing_hard_slots": ["pricing_model", "contacts"]
    })
    monitor.register_tenant_dossier(tenant_fallback, {
        "data_richness_score": 45,
        "missing_hard_slots": ["terms_guarantees"]
    })
    monitor.register_tenant_dossier(tenant_green, {
        "data_richness_score": 90,
        "missing_hard_slots": []
    })

    # Наполняем телеметрию для craft_pizza: 2 сбоя из 3 запросов (Fallback Rate 66.7%)
    fake_chunk = Chunk(chunk_id="c1", doc_id="d1", text="тест", token_count=10)
    ctx_ok = RAGContext(
        query="пицца маргарита",
        formatted_context="Маргарита 450р",
        chunks=[fake_chunk],
        top_score=0.85,
        has_sufficient_context=True,
        total_tokens=15
    )
    ctx_fallback = RAGContext(
        query="гарантия доставки 30 минут",
        formatted_context="",
        chunks=[],
        top_score=0.15,
        has_sufficient_context=False,
        fallback_message="Нет данных о гарантии",
        total_tokens=0
    )

    telemetry.record_query(tenant_fallback, "заказ", ctx_ok)
    telemetry.record_query(tenant_fallback, "гарантия", ctx_fallback)
    telemetry.record_query(tenant_fallback, "сроки доставки", ctx_fallback)

    # ── 1. Проверка оценки здоровья тенантов ──────────────────────────────
    print("--- 1. Evaluating Tenant Health Statuses ---")
    status_red = monitor.evaluate_tenant(tenant_red)
    assert status_red.needs_interrogation is True
    assert status_red.drs_score == 25
    assert status_red.target_slot == "pricing_model"
    assert "Red Tier" in (status_red.trigger_reason or "")
    print(f"   ✅ {tenant_red}: Корректно помечен для опроса ({status_red.trigger_reason})")

    status_fb = monitor.evaluate_tenant(tenant_fallback)
    assert status_fb.needs_interrogation is True
    assert status_fb.fallback_rate_pct >= 50.0
    assert status_fb.target_slot == "terms_guarantees"
    print(f"   ✅ {tenant_fallback}: Помечен из-за Fallback Rate {status_fb.fallback_rate_pct}%")

    status_green = monitor.evaluate_tenant(tenant_green)
    assert status_green.needs_interrogation is False
    print(f"   ✅ {tenant_green}: Здоровый тенант (DRS: {status_green.drs_score}) корректно пропущен\n")

    # ── 2. Активация микро-опроса для Красного тенанта ───────────────────
    print("--- 2. Triggering Micro-Interrogation for Red Tenant ---")
    trig_res = await monitor.trigger_micro_interrogation_async(tenant_red)
    assert trig_res.interrogation_sent is True
    assert trig_res.target_slot == "pricing_model"

    # Проверяем, что в SlotElevationHandler зафиксирован стейт ожидания
    saved_state = elevation_handler.get_interrogation_state(user_red)
    assert saved_state is not None
    assert saved_state["slot_name"] == "pricing_model"
    assert saved_state["tenant_id"] == tenant_red
    assert saved_state["current_drs"] == 25
    print("   ✅ Сообщение опроса отправлено владельцу.")
    print(f"   ✅ SlotElevationHandler переведен в состояние ожидания слота '{saved_state['slot_name']}'.\n")

    # ── 3. Защита от спама (Cooldown & Active State Check) ─────────────────
    print("--- 3. Testing Anti-Spam & Cooldown Protection ---")
    res_spam = await monitor.trigger_micro_interrogation_async(tenant_red)
    assert res_spam.interrogation_sent is False
    assert "уже активен" in (res_spam.trigger_reason or "")
    print("   ✅ Повторная отправка при активном стейте корректно заблокирована.")

    # ── 4. Замыкание контура: ответ владельца и повторный мониторинг ──────
    print("--- 4. Testing End-to-End Response Elevation & Re-evaluation ---")
    # Владелец присылает сообщение с ценами
    reply = "Мужская стрижка: 1500 руб, моделирование бороды: 900 руб."
    elev_res = await elevation_handler.handle_user_response(
        user_id=user_red,
        message_type="text",
        content=reply
    )
    assert elev_res.status == "success"
    assert elev_res.new_drs == 60  # 25 + 35 = 60 (Желтая зона)

    # Обновляем досье тенанта новым значением DRS и убираем pricing_model из missing
    monitor.register_tenant_dossier(tenant_red, {
        "data_richness_score": 60,
        "missing_hard_slots": ["contacts"]
    })

    # Повторная оценка тенанта: теперь DRS 60, опрос больше не требуется!
    re_status = monitor.evaluate_tenant(tenant_red)
    assert re_status.needs_interrogation is False
    assert re_status.drs_score == 60
    assert re_status.drs_tier == "yellow"
    print(f"   ✅ Факт подтвержден! DRS вырос до {re_status.drs_score} (Yellow Tier).")
    print("   ✅ Тенант больше не находится в красной зоне и не инициирует опросы.\n")

    # ── 5. Прогон полного фонового сканирования всех тенантов ───────────────
    print("--- 5. Testing Full Batch Scan (Celery Worker Core) ---")
    scan_summary = await monitor.scan_all_tenants_async()
    assert scan_summary["scanned_tenants"] >= 3
    # tenant_fallback должен триггернуться, tenant_red и tenant_green пропущены
    assert scan_summary["triggered_interrogations"] >= 1
    print(f"   ✅ Пакетное сканирование успешно: проверено {scan_summary['scanned_tenants']} тенантов, "
          f"инициировано опросов: {scan_summary['triggered_interrogations']}.\n")

    # ── 6. Запуск через Celery Task API ────────────────────────────────────
    print("--- 6. Testing Celery Task Execution ---")
    celery_result = monitor_drs_and_trigger_interrogation_task(
        min_drs_threshold=40,
        max_fallback_rate_pct=50.0,
        tenant_ids=["craft_pizza"]
    )
    assert celery_result["scanned_tenants"] >= 1
    assert "task_id" in celery_result
    print("   ✅ Celery таска monitor_drs_and_trigger_interrogation_task выполнена успешно.")
    print(f"   ✅ Результат таски: {celery_result['scanned_tenants']} проверено, ID: {celery_result['task_id']}\n")

    print("🎉 ВСЕ ТЕСТЫ DRS HEALTH MONITOR И ПЕРИОДИЧЕСКОГО ВОРКЕРА ПРОЙДЕНЫ НА 100%!")


if __name__ == "__main__":
    asyncio.run(test_drs_health_monitor_lifecycle())

"""
File: ai/scripts/test_slot_elevation_handler.py
Интеграционный тест для SlotElevationHandler (Micro-Interrogation Response Engine):
1. State Tracking: корректное сохранение и сброс состояния ожидания ответа.
2. Text Response Processing: извлечение цен из текста, элевация до Hard Fact (confidence=1.0).
3. Voice Response Processing: обработка голосовых сообщений, транскрибация и элевация.
4. Inline Button Fallback: клик по кнопке [Прайс по запросу] -> фиксация FallbackStrategy.
5. Passive Messages: игнорирование обычных сообщений вне контекста опроса.
6. End-to-End RAG Closure: проверка сохранения фактов в слой hard_fact и сброса кэша.
"""

import sys
import os
import asyncio
from typing import Dict, Any

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from schemas.provenance_contracts import (
    FieldCategoryEnum,
    FieldProvenanceEnum,
    FallbackStrategyEnum
)
from rag.models import DocCategoryEnum, TrustTierEnum, Document
from rag.pipeline import CleanRAGPipeline
from services.rag_manager import BrandKnowledgeManager, InMemoryEventBus
from skills.slot_elevation_handler import SlotElevationHandler, SlotElevationResult
from analytics.rag_telemetry import RAGTelemetryTracker


async def test_slot_elevation_lifecycle():
    print("🚀 СТАРТ ТЕСТИРОВАНИЯ ХЭНДЛЕРА ЭЛЕВАЦИИ СЛОТОВ (SLOT ELEVATION ENGINE)\n")

    # 1. Инициализация контура RAG и Event Bus
    rag = CleanRAGPipeline(min_confidence_threshold=0.30)
    event_bus = InMemoryEventBus()
    bkm = BrandKnowledgeManager(rag_pipeline=rag, event_bus=event_bus)

    bus_events = []
    event_bus.subscribe("knowledge_updated", lambda payload: bus_events.append(payload))

    handler = SlotElevationHandler(rag_pipeline=rag, rag_manager=bkm)

    user_id = "tg_user_88412"
    tenant_id = "sweet_bakery"

    # ── Сценарий 1: Игнорирование сообщений вне опроса ─────────────────────
    print("--- 1. Testing Unrelated Message (Passive State) ---")
    res_unrelated = await handler.handle_user_response(
        user_id=user_id,
        message_type="text",
        content="Привет! Какая погода в Москве?"
    )
    assert res_unrelated.status == "ignored"
    assert res_unrelated.is_interrogation is False
    print("   ✅ Сообщение вне контекста опроса корректно проигнорировано.\n")

    # ── Сценарий 2: Текстовый ответ с ценами (Text Elevation) ──────────────
    print("--- 2. Testing Text Response & Pricing Elevation ---")
    # Инициализация опроса: у пекарни нет цен (DRS = 35, Red Tier)
    handler.set_interrogation_state(
        user_id=user_id,
        tenant_id=tenant_id,
        slot_name="pricing_model",
        category="hard_fact",
        question="Назовите стоимость куличей и выпечки?",
        current_drs=35
    )

    state = handler.get_interrogation_state(user_id)
    assert state is not None
    assert state["slot_name"] == "pricing_model"

    # Пользователь отправляет текст с ценами
    user_reply = "Кулич авторский 500г: 1230 руб, пасха творожная: 1450 руб, эклеры: 320 руб."
    elevation_res = await handler.handle_user_response(
        user_id=user_id,
        message_type="text",
        content=user_reply
    )

    assert elevation_res.status == "success"
    assert elevation_res.is_interrogation is True
    assert elevation_res.elevated_field is not None
    assert elevation_res.elevated_field.confidence == 1.0
    assert elevation_res.elevated_field.source == FieldProvenanceEnum.EXTRACTED
    assert elevation_res.old_drs == 35
    assert elevation_res.new_drs == 70  # +35 баллов за цены
    assert elevation_res.drs_tier == "yellow"
    assert "1230 руб" in str(elevation_res.elevated_field.value)

    # Проверяем очистку стейта
    assert handler.get_interrogation_state(user_id) is None, "State must be cleared after success"

    # Проверяем, что Event Bus получил нотификацию
    assert len(bus_events) >= 1
    assert bus_events[-1]["tenant_id"] == tenant_id

    # Проверяем, что Clean RAG теперь видит этот Hard Fact в слое hard_fact!
    rag_ctx = await rag.query_stratified_context_async("кулич цена стоимость", tenant_id=tenant_id)
    assert rag_ctx.has_sufficient_context is True
    assert rag_ctx.has_hard_facts is True
    assert any("1230 руб" in c.text for c in rag_ctx.get_layer(DocCategoryEnum.HARD_FACT.value))

    print("   ✅ Текстовый ответ успешно возведен в ранг Hard Fact (confidence=1.0).")
    print(f"   ✅ DRS вырос: {elevation_res.old_drs} 🔴 -> {elevation_res.new_drs} 🟡.")
    print("   ✅ Clean RAG мгновенно проиндексировал факт в слой hard_fact.\n")

    # ── Сценарий 3: Голосовой ответ (Voice / STT Elevation) ────────────────
    print("--- 3. Testing Voice Response & Guarantee Elevation ---")
    # Новый опрос по гарантии доставки (DRS = 70, Yellow Tier)
    handler.set_interrogation_state(
        user_id=user_id,
        tenant_id=tenant_id,
        slot_name="terms_guarantees",
        category="hard_fact",
        question="Какие у вас сроки и гарантия свежести?",
        current_drs=70
    )

    # Имитация голосового сообщения
    voice_audio_transcript = "Гарантия свежести выпечки 72 часа, бесплатный возврат если кулич черствый."
    voice_res = await handler.handle_user_response(
        user_id=user_id,
        message_type="voice",
        content=voice_audio_transcript
    )

    assert voice_res.status == "success"
    assert voice_res.new_drs >= 100  # Достигли Green Tier!
    assert voice_res.drs_tier == "green"
    assert "72 часа" in str(voice_res.elevated_field.value)

    # Проверяем попадание в RAG
    rag_ctx_terms = await rag.query_stratified_context_async("гарантия возврат свежесть", tenant_id=tenant_id)
    assert any("72 часа" in c.text for c in rag_ctx_terms.get_layer(DocCategoryEnum.HARD_FACT.value))

    print("   ✅ Голосовое сообщение обработано, факты гарантий зафиксированы.")
    print(f"   ✅ DRS достиг зеленой зоны: {voice_res.new_drs}/100 🟢.\n")

    # ── Сценарий 4: Клик по кнопке [Прайс по запросу] ─────────────────────
    print("--- 4. Testing Inline Button Click (Fallback Strategy) ---")
    handler.set_interrogation_state(
        user_id=user_id,
        tenant_id=tenant_id,
        slot_name="pricing_model",
        category="hard_fact",
        current_drs=60
    )

    button_res = await handler.handle_user_response(
        user_id=user_id,
        message_type="button",
        content="action:price_on_request"
    )

    assert button_res.status == "fallback_set"
    assert button_res.elevated_field is not None
    assert button_res.elevated_field.fallback_strategy == FallbackStrategyEnum.PRICE_ON_REQUEST
    assert handler.get_interrogation_state(user_id) is None

    print("   ✅ Клик по инлайн-кнопке корректно зафиксировал стратегию PRICE_ON_REQUEST.\n")

    # ── Сценарий 5: Пропуск вопроса ────────────────────────────────────────
    print("--- 5. Testing Question Skip ---")
    handler.set_interrogation_state(
        user_id=user_id,
        tenant_id=tenant_id,
        slot_name="phones",
        current_drs=60
    )

    skip_res = await handler.handle_user_response(
        user_id=user_id,
        message_type="button",
        content="action:skip"
    )

    assert skip_res.status == "skipped"
    assert handler.get_interrogation_state(user_id) is None
    print("   ✅ Пропуск вопроса корректно очистил состояние без побочных эффектов.\n")

    print("🎉 ВСЕ ТЕСТЫ ЭЛЕВАЦИИ СЛОТОВ И ОБРАБОТКИ ОТВЕТОВ ПРОЙДЕНЫ НА 100%!")


if __name__ == "__main__":
    asyncio.run(test_slot_elevation_lifecycle())

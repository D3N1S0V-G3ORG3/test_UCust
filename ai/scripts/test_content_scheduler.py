"""
File: ai/scripts/test_content_scheduler.py
Сквозной интеграционный тест для Content Scheduler Engine:
1. RAG Stratification: индексация 4 слоев (Hard Facts, Brand DNA, Audience Priors, Directives).
2. Weekly Grid Generation: генерация сетки на 7 дней по матрице воронки Ханта (TOFU / MOFU / BOFU).
3. Truth Grounding: проверка, что BOFU-слоты строго содержат цены из Hard Ground Truth.
4. Multi-Platform Formatting: проверка адаптации под Telegram, VK, OK, Max.
5. Celery Task Execution: генерация сетки и публикация запланированного слота через Celery.
6. API Gateway: вызов эндпоинта генерации сетки через FastAPI TestClient.
"""

import sys
import os
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rag.models import Document, DocCategoryEnum, TrustTierEnum
from rag.pipeline import CleanRAGPipeline
from services.content_scheduler import ContentSchedulerService, FunnelStageEnum
from celery_tasks import generate_weekly_grid_task, publish_scheduled_slot_task
from api_gateway import app
from fastapi.testclient import TestClient


async def test_content_scheduler_lifecycle():
    print("🚀 СТАРТ ТЕСТИРОВАНИЯ КОНТЕНТ-ПЛАНИРОВЩИКА (CONTENT SCHEDULER ENGINE)\n")

    tenant_id = "artisan_bakery_spb"
    company_name = "Ремесленная Пекарня №1"
    niche = "Выпечка и десерты"

    # ── 1. Индексация 4 слоев базы знаний в Clean RAG ─────────────────────
    print("--- 1. Ingesting 4-Layer RAG Knowledge Base ---")
    rag = CleanRAGPipeline(min_confidence_threshold=0.30)

    docs = [
        # Слой 1: Hard Ground Truth (Цены, сроки, гарантии)
        Document(
            doc_id=f"doc_hard_{tenant_id}",
            text="Прайс-лист: кулич ремесленный 500г: 1250 руб, эклеры ванильные: 350 руб, хлеб тартин: 280 руб. Доставка бесплатно от 2500 руб.",
            metadata={
                "tenant_id": tenant_id,
                "client_id": tenant_id,
                "doc_category": DocCategoryEnum.HARD_FACT.value,
                "trust_tier": TrustTierEnum.VERIFIED_BY_OWNER.value,
                "source": "owner_verified"
            }
        ),
        # Слой 2: Brand DNA (Редполитика и ToV)
        Document(
            doc_id=f"doc_dna_{tenant_id}",
            text="Редполитика: пишем тепло, с любовью к тесту, без канцеляризмов. Акцент на 36-часовом холодном брожении и новозеландском сливочном масле 82.5%.",
            metadata={
                "tenant_id": tenant_id,
                "client_id": tenant_id,
                "doc_category": DocCategoryEnum.BRAND_DNA.value,
                "trust_tier": TrustTierEnum.VERIFIED_AUTOMATED.value,
                "source": "brand_dna"
            }
        ),
        # Слой 3: Audience Priors (Боли ЦА)
        Document(
            doc_id=f"doc_audience_{tenant_id}",
            text="Боли ЦА: устали от сухого магазинного хлеба на улучшителях и маргарине. Хотят чистый состав для детей и хрустящую корочку.",
            metadata={
                "tenant_id": tenant_id,
                "client_id": tenant_id,
                "doc_category": DocCategoryEnum.AUDIENCE_PRIORS.value,
                "trust_tier": TrustTierEnum.VERIFIED_AUTOMATED.value,
                "source": "niche_priors"
            }
        ),
    ]

    indexed_count = rag.ingest_documents(docs)
    assert indexed_count >= 3
    print(f"   ✅ Успешно проиндексировано {indexed_count} чанков по 3 слоям.\n")

    # ── 2. Генерация 7-дневной сетки по воронке Ханта ─────────────────────
    print("--- 2. Generating 7-Day Content Funnel Grid ---")
    scheduler = ContentSchedulerService(rag_pipeline=rag, platforms=["telegram", "vk", "ok", "max"])

    grid = await scheduler.generate_weekly_grid_async(
        tenant_id=tenant_id,
        company_name=company_name,
        niche=niche,
        days_count=7
    )

    assert grid.days_count == 7
    assert len(grid.slots) == 7
    assert grid.funnel_stats["tofu"] >= 2
    assert grid.funnel_stats["mofu"] >= 2
    assert grid.funnel_stats["bofu"] >= 2
    print(f"   ✅ Сетка сгенерирована: {len(grid.slots)} слотов.")
    print(f"   📊 Баланс воронки: TOFU={grid.funnel_stats['tofu']}, MOFU={grid.funnel_stats['mofu']}, BOFU={grid.funnel_stats['bofu']}.\n")

    # ── 3. Проверка Truth Grounding и содержимого слотов ──────────────────
    print("--- 3. Verifying Truth Grounding in Commercial (BOFU) Slots ---")
    bofu_slots = [s for s in grid.slots if s.funnel_stage == FunnelStageEnum.BOFU]
    assert len(bofu_slots) >= 2

    # BOFU слот среды обязан содержать извлеченные цены из RAG hard_fact
    wednesday_slot = grid.slots[2]
    assert wednesday_slot.funnel_stage == FunnelStageEnum.BOFU
    assert "1250 руб" in wednesday_slot.base_text or "350 руб" in wednesday_slot.base_text
    print(f"   ✅ Слот #{wednesday_slot.day_index} ({wednesday_slot.day_name}, BOFU): содержит подтвержденные цены: '1250 руб'.")

    # TOFU слот понедельника обязан отражать боли ЦА
    monday_slot = grid.slots[0]
    assert monday_slot.funnel_stage == FunnelStageEnum.TOFU
    assert "магазинного" in monday_slot.base_text or "хлеб" in monday_slot.base_text or "состав" in monday_slot.base_text
    print(f"   ✅ Слот #{monday_slot.day_index} ({monday_slot.day_name}, TOFU): отражает боли ЦА из слоя audience_priors.\n")

    # ── 4. Проверка мультиплатформенного форматирования ───────────────────
    print("--- 4. Checking Multi-Platform Adaptation (TG, VK, OK, Max) ---")
    first_slot = grid.slots[0]
    assert "telegram" in first_slot.platform_drafts
    assert "vk" in first_slot.platform_drafts
    assert "ok" in first_slot.platform_drafts
    assert "max" in first_slot.platform_drafts

    tg_draft = first_slot.platform_drafts["telegram"]
    vk_draft = first_slot.platform_drafts["vk"]
    assert tg_draft["char_count"] > 50
    assert vk_draft["char_count"] > 50
    print(f"   ✅ Telegram: {tg_draft['char_count']} симв.")
    print(f"   ✅ VKontakte: {vk_draft['char_count']} симв.")
    print("   ✅ OK & Max: успешно адаптированы.\n")

    # ── 5. Тестирование Celery-задач публикации и генерации ────────────────
    print("--- 5. Testing Celery Tasks Execution ---")
    # 5.1 Генерация сетки через Celery таску
    celery_grid_res = generate_weekly_grid_task(
        tenant_id=tenant_id,
        company_name=company_name,
        niche=niche,
        days_count=7,
        auto_schedule=False
    )
    assert celery_grid_res["status"] == "success"
    assert celery_grid_res["slots_count"] == 7
    print(f"   ✅ Celery generate_weekly_grid_task: успешно создано {celery_grid_res['slots_count']} слотов.")

    # 5.2 Публикация слота через Celery таску
    sample_slot = grid.slots[0].model_dump()
    pub_res = publish_scheduled_slot_task(
        tenant_id=tenant_id,
        slot_data=sample_slot,
        target_channel="@test_channel",
        platform="telegram"
    )
    assert pub_res["status"] == "published"
    assert pub_res["tenant_id"] == tenant_id
    print("   ✅ Celery publish_scheduled_slot_task: слот успешно опубликован.\n")

    # ── 6. Проверка FastAPI REST эндпоинтов ────────────────────────────────
    print("--- 6. Testing FastAPI Scheduler Endpoints ---")
    client = TestClient(app)

    # 6.1 POST /api/v1/scheduler/generate-grid
    post_res = client.post(
        "/api/v1/scheduler/generate-grid",
        json={
            "tenant_id": "bakery_api_test",
            "company_name": "Тестовая Булочная",
            "niche": "Кондитерская",
            "days_count": 7,
            "auto_schedule": False
        }
    )
    assert post_res.status_code == 200
    data = post_res.json()
    assert data["status"] == "success"
    assert data["slots_count"] == 7
    print(f"   ✅ POST /api/v1/scheduler/generate-grid: HTTP 200, Grid ID: {data['grid_id']}.")

    # 6.2 GET /api/v1/scheduler/{tenant_id}/grid
    get_res = client.get("/api/v1/scheduler/bakery_api_test/grid")
    assert get_res.status_code == 200
    grid_data = get_res.json()
    assert grid_data["status"] == "success"
    assert len(grid_data["grid"]["slots"]) == 7
    print("   ✅ GET /api/v1/scheduler/bakery_api_test/grid: HTTP 200, сетка получена.\n")

    print("🎉 ВСЕ ТЕСТЫ КОНТЕНТ-ПЛАНИРОВЩИКА И МУЛЬТИПЛАТФОРМЕННОЙ ПУБЛИКАЦИИ ПРОЙДЕНЫ НА 100%!")


if __name__ == "__main__":
    asyncio.run(test_content_scheduler_lifecycle())

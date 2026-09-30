"""
File: tests/test_api_gateway_e2e_suite.py
Сквозной интеграционный тест всех 6 фаз API Gateway UCust.AI:
- Фаза 1: Инфраструктура, Health-check и Очереди (System & Observability)
- Фаза 2: Память и Инжестинг (Knowledge Base & Clean RAG)
- Фаза 3: Онбординг и Сбор данных (Collectors & HITL)
- Фаза 4: Ядро генерации контента и отложенный рендер (Content Generation & Lazy Rendering)
- Фаза 5: Интерактивные инструменты, Стратегия и Радар (Auxiliary APIs)
- Фаза 6: Real-time тестирование (WebSockets)
"""

from __future__ import annotations

import os
import sys
import json
import pytest
from unittest.mock import AsyncMock, patch
from starlette.testclient import TestClient

# Добавляем путь к корню и ai в sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ai")))

from ai.api_gateway import app


@pytest.fixture(scope="module")
def client():
    with patch("ai.api_gateway.queue_manager.start_worker", new_callable=AsyncMock), \
         patch("ai.api_gateway.queue_manager.stop_worker", new_callable=AsyncMock), \
         patch("ai.api_gateway.vram_scheduler.warmup_gpu_pipelines", new_callable=AsyncMock):
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client


# ============================================================================
# ФАЗА 1: Инфраструктура, Health-check и Очереди (System & Observability)
# ============================================================================

def test_phase1_liveness_readiness_health(client: TestClient):
    """
    Проверка Liveness / Readiness проб.
    """
    resp_root = client.get("/health")
    assert resp_root.status_code == 200
    data = resp_root.json()
    assert data.get("status") in ["healthy", "ok", "success"]

    resp_ai_health = client.get("/api/v1/ai/health")
    assert resp_ai_health.status_code == 200
    assert resp_ai_health.json().get("status") in ["healthy", "ok", "success"]


def test_phase1_metrics_and_observability(client: TestClient):
    """
    Проверка экспорта метрик Prometheus.
    """
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert len(resp.text) > 0


def test_phase1_gpu_status_diagnostics(client: TestClient):
    """
    Проверка доступности и статуса пула GPU-нод ComfyUI.
    """
    resp = client.get("/api/v1/ai/system/gpu-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") in ["healthy", "ok", "available"] or "vram" in data or "gpu_device" in data


def test_phase1_queue_stats(client: TestClient):
    """
    Проверка метрик очередей задач.
    """
    resp = client.get("/api/v1/ai/queue/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "queue_length" in data or "active_tasks" in data or "status" in data


# ============================================================================
# ФАЗА 2: Память и Инжестинг (Knowledge Base & Clean RAG)
# ============================================================================

def test_phase2_rag_ingest_and_query(client: TestClient):
    """
    Загрузка фактов в базу знаний и семантический поиск.
    """
    # 1. Ingest факта
    ingest_payload = {
        "documents": [
            {
                "doc_id": "fact_curex_500ml",
                "text": "Маска Curex Therapy 500мл содержит натуральный бетаин, витамин E и пантенол для интенсивного восстановления структуры волос.",
                "source": "pim_catalog",
                "metadata": {
                    "project_id": "estel_pro",
                    "sku_id": "sku_curex_500ml",
                    "category": "hair_mask"
                }
            }
        ]
    }
    resp_ingest = client.post("/api/v1/ai/rag/ingest", json=ingest_payload)
    assert resp_ingest.status_code == 200
    data_ingest = resp_ingest.json()
    assert data_ingest.get("status") == "success"
    assert data_ingest.get("indexed_count") == 1

    # 2. Query факта
    query_payload = {
        "query": "Какой состав у восстанавливающей маски Curex?",
        "top_k": 3
    }
    resp_query = client.post("/api/v1/ai/rag/query", json=query_payload)
    assert resp_query.status_code == 200
    data_query = resp_query.json()
    assert "query" in data_query
    assert "has_sufficient_context" in data_query


# ============================================================================
# ФАЗА 3: Онбординг и Сбор данных (Collectors & HITL)
# ============================================================================

def test_phase3_project_analysis_and_commit(client: TestClient):
    """
    Мультимодальный анализ бренда и фиксация профиля (Human-in-the-Loop Commit).
    """
    analyze_payload = {
        "source_url": "https://t.me/kofeina_aromat",
        "niche_hint": "Кофейня спешелти",
        "city": "Санкт-Петербург"
    }
    resp_analyze = client.post("/api/v1/projects/analyze", json=analyze_payload)
    assert resp_analyze.status_code == 200
    data_analyze = resp_analyze.json()
    assert data_analyze.get("status") == "success"
    assert "project_profile_draft" in data_analyze

    # HITL Commit 5-экранного профиля
    commit_payload = {
        "data": {
            "about": {
                "name": "Кофейня Аромат",
                "niche": "Спешелти кофейня",
                "positioning": "Свежая обжарка и крафтовые десерты",
                "city": "Санкт-Петербург",
                "description": "Уютная кофейня в центре города"
            },
            "market": {
                "competitors": ["Даблби", "Surf Coffee"],
                "geography": "Санкт-Петербург",
                "audience_segment": "Молодые специалисты 20-40 лет",
                "trends": ["Альтернативное молоко", "Фильтр-кофе"]
            },
            "swot": {
                "strengths": ["Собственная обжарка"],
                "weaknesses": ["Мало посадочных мест"],
                "opportunities": ["Запуск доставки"],
                "threats": ["Рост цен на зерно"]
            },
            "services": [
                {
                    "name": "Фирменный флэт уайт",
                    "description": "На двойном эспрессо",
                    "price": "320 руб."
                }
            ],
            "goals": {
                "content_goals": ["Привлечение новых гостей"],
                "tone_of_voice": ["Дружелюбный", "Экспертный"]
            }
        }
    }
    resp_commit = client.post("/api/v1/projects/kofeina_aromat/commit", json=commit_payload)
    assert resp_commit.status_code == 200
    data_commit = resp_commit.json()
    assert data_commit.get("status") == "success"
    assert data_commit.get("project_id") == "kofeina_aromat"


def test_phase3_universal_collector_parse(client: TestClient):
    """
    Проверка универсального парсера источников.
    """
    parse_payload = {
        "source_type": "telegram",
        "target": "@estel_official",
        "limit": 5
    }
    resp = client.post("/api/v1/collectors/parse", json=parse_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") in ["success", "completed"]


# ============================================================================
# ФАЗА 4: Ядро генерации контента и отложенный рендер (Content & Lazy Render)
# ============================================================================

def test_phase4_direct_draft_generation(client: TestClient):
    """
    Генерация черновика поста со статусом DRAFT_TEXT (0 GPU Cost).
    """
    draft_payload = {
        "brand_id": "estel_pro",
        "company_name": "Estel Professional",
        "industry": "b2c_lifestyle",
        "tier": "pro",
        "brand_props": ["glass vanity", "minimal scandi"],
        "tone_of_voice": "Экспертный, заботливый",
        "user_raw_intent": "Новая терапевтическая маска Curex 500мл",
        "format": "single_shot"
    }
    resp = client.post("/api/v1/content/draft", json=draft_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "post_id" in data
    assert data.get("status") == "draft_text"
    assert "vram_cost_mb" in data


def test_phase4_lazy_rendering_execution(client: TestClient):
    """
    Отложенный рендеринг ассета в ComfyUI после утверждения черновика.
    """
    # 1. Создаем черновик
    draft_payload = {
        "brand_id": "estel_pro",
        "company_name": "Estel Professional",
        "industry": "b2c_lifestyle",
        "tier": "pro",
        "brand_props": ["marble shelf"],
        "tone_of_voice": "Экспертный",
        "user_raw_intent": "Шампунь Otium Aqua",
        "format": "single_shot"
    }
    resp_draft = client.post("/api/v1/content/draft", json=draft_payload)
    assert resp_draft.status_code == 200
    post_id = resp_draft.json().get("post_id")

    # 2. Рендерим ассет (Lazy Rendering)
    resp_render = client.post(f"/api/v1/content/render/{post_id}")
    assert resp_render.status_code == 200
    data_render = resp_render.json()
    assert data_render.get("status") == "success"
    assert data_render.get("post_id") == post_id

    # 3. Проверяем статус поста
    resp_post = client.get(f"/api/v1/content/post/{post_id}")
    assert resp_post.status_code == 200
    data_post = resp_post.json()
    assert data_post.get("post_id") == post_id


# ============================================================================
# ФАЗА 5: Интерактивные инструменты, Стратегия и Радар (Auxiliary APIs)
# ============================================================================

def test_phase5_ideas_bank_and_radar(client: TestClient):
    """
    Банк идей и синхронизация ситуативного радара трендов.
    """
    resp_bank = client.get("/api/v1/ideas/bank?niche=Салонная косметика")
    assert resp_bank.status_code == 200

    resp_radar = client.post("/api/v1/ideas/bank/sync-radar", json={"niche": "Салонная косметика"})
    assert resp_radar.status_code == 200
    assert resp_radar.json().get("status") == "success"


def test_phase5_poll_generation(client: TestClient):
    """
    Генерация интерактивного опроса/квиза.
    """
    poll_payload = {
        "topic": "Как часто вы делаете салонные процедуры ухода?",
        "niche": "Салоны красоты",
        "company_name": "Estel"
    }
    resp = client.post("/api/v1/content/poll/generate", json=poll_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "success"
    assert "poll" in data


def test_phase5_strategy_and_critic(client: TestClient):
    """
    Построение стратегии и запуск факт-чекинг критика.
    """
    strat_payload = {
        "user_id": "usr_test",
        "task_type": "plan_content",
        "payload": {
            "company_name": "Estel Professional",
            "niche": "Салонный уход"
        }
    }
    resp_strat = client.post("/api/v1/orchestrator/execute", json=strat_payload)
    assert resp_strat.status_code == 200

    critic_payload = {
        "text": "Маска Curex восстанавливает структуру волос.",
        "fact_sheet": {"key_specs": ["Пантенол", "Витамин E"]}
    }
    resp_critic = client.post("/api/v1/ai/critic/review", json=critic_payload)
    assert resp_critic.status_code == 200


# ============================================================================
# ФАЗА 6: Real-time тестирование (WebSockets)
# ============================================================================

def test_phase6_websocket_realtime_session(client: TestClient):
    """
    Проверка интерактивного обмена событиями по WebSocket /ws/ai/session/{session_id}.
    """
    session_id = "test_ws_session_12345"
    with client.websocket_connect(f"/ws/ai/session/{session_id}") as websocket:
        # При подключении сервер присылает приветствие онбординга
        greeting_data = websocket.receive_text()
        assert len(greeting_data) > 0
        parsed_greeting = json.loads(greeting_data)
        assert "session_id" in parsed_greeting or "step" in parsed_greeting or "payload" in parsed_greeting

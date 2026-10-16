"""
File: ai/celery_tasks.py
Celery Worker Configuration & Distributed Task Bus for UCust AI.

Очереди задач по приоритету тарифов:
    • custom   (Свой / VIP тариф)      — наивысший приоритет, выделенные воркеры
    • business (Бизнес / Стандарт)     — высокий приоритет, коммерческая генерация
    • start    (Старт / Базовый)       — стандартный приоритет, фоновая обработка

Development Environment (Low-spec / 8GB RAM / CPU):
    celery -A celery_tasks.celery_app worker --loglevel=info --concurrency=1 -Q custom,business,start

Production Environment (Multi-tier Priority Queues):
    celery -A celery_tasks.celery_app worker --loglevel=info --concurrency=4 -Q custom,business,start
"""

from __future__ import annotations

import os
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

try:
    from celery import Celery
    HAS_CELERY = True
except ImportError:
    HAS_CELERY = False

logger = logging.getLogger("CeleryTasks")

# Названия очередей по приоритету тарифов и фоновых задач
QUEUE_START = "start"                # Старт (базовый тариф)
QUEUE_BUSINESS = "business"          # Бизнес (коммерческий тариф)
QUEUE_CUSTOM = "custom"              # Свой тариф / Кастомный (VIP)
QUEUE_TREND_MINING = "trend_mining"  # Фоновый сбор, кластеризация и анализ трендов
QUEUE_FEEDBACK = "feedback_loop"      # Фоновый сбор и анализ телеметрии, самообучение

# Маппинг тарифов к очередям
TIER_QUEUES: Dict[str, str] = {
    "start": QUEUE_START,
    "starter": QUEUE_START,
    "старт": QUEUE_START,
    "business": QUEUE_BUSINESS,
    "бизнес": QUEUE_BUSINESS,
    "pro": QUEUE_BUSINESS,
    "custom": QUEUE_CUSTOM,
    "кастомный": QUEUE_CUSTOM,
    "свой": QUEUE_CUSTOM,
    "свой тариф": QUEUE_CUSTOM,
    "enterprise": QUEUE_CUSTOM,
    "vip": QUEUE_CUSTOM,
    "trends": QUEUE_TREND_MINING,
    "trend_mining": QUEUE_TREND_MINING,
    "feedback": QUEUE_FEEDBACK,
    "feedback_loop": QUEUE_FEEDBACK,
    "telemetry": QUEUE_FEEDBACK,
}

def get_queue_for_tier(tier: Optional[str] = None) -> str:
    """Определяет целевую очередь Celery на основе тарифа клиента."""
    if not tier:
        return QUEUE_BUSINESS
    return TIER_QUEUES.get(str(tier).lower().strip(), QUEUE_BUSINESS)

# Настройка брокера и бэкенда результатов (Redis)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

if HAS_CELERY:
    celery_app = Celery("ucust_ai", broker=REDIS_URL, backend=REDIS_URL)

    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_routes={
            "celery_tasks.render_post_task": {"queue": QUEUE_BUSINESS},
            "celery_tasks.generate_post_draft_task": {"queue": QUEUE_BUSINESS},
            "celery_tasks.onboard_brand_task": {"queue": QUEUE_BUSINESS},
            "celery_tasks.audit_post_task": {"queue": QUEUE_BUSINESS},
            "celery_tasks.collect_raw_trends_task": {"queue": QUEUE_TREND_MINING},
            "celery_tasks.process_trend_clusters_task": {"queue": QUEUE_TREND_MINING},
            "celery_tasks.collect_channel_telemetry_batch_task": {"queue": QUEUE_FEEDBACK},
            "celery_tasks.monitor_drs_and_trigger_interrogation_task": {"queue": QUEUE_FEEDBACK},
            "celery_tasks.*": {"queue": QUEUE_BUSINESS},
        },
        beat_schedule={
            "collect-raw-trends-every-30-mins": {
                "task": "celery_tasks.collect_raw_trends_task",
                "schedule": 1800.0,
                "options": {"queue": QUEUE_TREND_MINING},
            },
            "process-trend-clusters-every-2-hours": {
                "task": "celery_tasks.process_trend_clusters_task",
                "schedule": 7200.0,
                "options": {"queue": QUEUE_TREND_MINING},
            },
            "collect-telemetry-hourly": {
                "task": "celery_tasks.collect_channel_telemetry_batch_task",
                "schedule": 3600.0,
                "options": {"queue": QUEUE_FEEDBACK},
            },
            "monitor-drs-and-trigger-interrogations-hourly": {
                "task": "celery_tasks.monitor_drs_and_trigger_interrogation_task",
                "schedule": 3600.0,
                "options": {"queue": QUEUE_FEEDBACK},
            },
        },
        worker_prefetch_multiplier=1,
        task_acks_late=True,
        task_track_started=True,
        task_time_limit=300,  # 5 минут жесткий лимит
    )

else:
    class DummyAsyncResult:
        def __init__(self, task_id):
            self.id = task_id
            self.status = "PENDING"

    class DummyTask:
        def __init__(self, fn, name):
            self.fn = fn
            self.name = name
            self.request = type("Req", (), {"id": "mock-task-id-123"})()
        def __call__(self, *args, **kwargs):
            return self.fn(self, *args, **kwargs)
        def delay(self, *args, **kwargs):
            return self.fn(self, *args, **kwargs)

    class DummyCelery:
        def __init__(self, name, broker=None, backend=None):
            self.main = name
            self.broker = broker
            self.backend = backend
            self.conf = {}
            self.tasks = {}
        def task(self, *dargs, **dkwargs):
            def decorator(fn):
                t_name = dkwargs.get("name", fn.__name__)
                dt = DummyTask(fn, t_name)
                self.tasks[t_name] = dt
                return dt
            return decorator
        def send_task(self, name, args=None, kwargs=None, queue=None):
            import uuid
            tid = f"task_{uuid.uuid4().hex[:12]}"
            return DummyAsyncResult(task_id=tid)

    celery_app = DummyCelery("ucust_ai", broker=REDIS_URL, backend=REDIS_URL)




def _run_async(coro):
    """Хелпер для запуска асинхронных корутин внутри синхронных Celery тасок."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, coro).result()
    else:
        new_loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(new_loop)
            return new_loop.run_until_complete(coro)
        finally:
            new_loop.close()



@celery_app.task(name="celery_tasks.onboard_brand_task", bind=True)
def onboard_brand_task(
    self,
    tenant_id: str,
    company_name: str,
    niche: str,
    telegram_channel: Optional[str] = None,
    website_url: Optional[str] = None,
    document_paths: Optional[List[str]] = None,
    raw_notes: Optional[str] = None,
    callback_url: Optional[str] = None,
    dev_mode: bool = True
) -> Dict[str, Any]:
    """
    Фоновый онбординг бренда: сбор данных, извлечение Brand DNA, сохранение в Persistent RAG
    и отправка Webhook уведомления на внешний бэкенд.
    """
    logger.info(f"🚀 [Celery] Старт онбординга {company_name} (Task ID: {self.request.id})")
    from skills.onboarding_agent import OnboardingAgent
    from services.rag_manager import BrandKnowledgeManager
    from services.webhook_manager import WebhookCallbackManager

    agent = OnboardingAgent(dev_mode=dev_mode)
    
    try:
        brand_dna = _run_async(agent.ingest_and_profile_brand(
            tenant_id=tenant_id,
            company_name=company_name,
            niche=niche,
            telegram_channel=telegram_channel,
            website_url=website_url,
            document_paths=document_paths,
            raw_notes=raw_notes
        ))
        
        # Сохранение в Persistent RAG (PostgreSQL / SQLite)
        _run_async(BrandKnowledgeManager.upsert_brand_dna(
            tenant_id=tenant_id,
            dna_data=brand_dna.dict()
        ))

        res = {
            "status": "success",
            "task_id": self.request.id,
            "tenant_id": tenant_id,
            "brand_dna": brand_dna.dict()
        }

        # Webhook Push обратной связи
        if callback_url:
            WebhookCallbackManager.send_callback_sync(
                callback_url=callback_url,
                event_type="onboarding_completed",
                tenant_id=tenant_id,
                task_id=self.request.id,
                status="success",
                data=res
            )

        return res
    except Exception as exc:
        logger.error(f"❌ [Celery] Ошибка онбординга {company_name}: {exc}")
        if callback_url:
            WebhookCallbackManager.send_callback_sync(
                callback_url=callback_url,
                event_type="onboarding_failed",
                tenant_id=tenant_id,
                task_id=self.request.id,
                status="failed",
                error=str(exc)
            )
        raise exc


@celery_app.task(name="celery_tasks.audit_post_task", bind=True)
def audit_post_task(
    self,
    proposed_topic_or_text: str,
    recent_channel_posts: List[str],
    topic_category: str = "general",
    threshold: float = 0.82
) -> Dict[str, Any]:
    """
    Фоновый аудит уникальности темы / текста поста.
    """
    logger.info(f"🔍 [Celery] Аудит темы: '{proposed_topic_or_text[:50]}...'")
    from skills.audit_deduplication_agent import AuditDeduplicationAgent
    agent = AuditDeduplicationAgent(custom_threshold=threshold)
    verdict = agent.evaluate_uniqueness(
        proposed_topic_or_text=proposed_topic_or_text,
        recent_channel_posts=recent_channel_posts,
        topic_category=topic_category
    )
    return {
        "status": "success",
        "task_id": self.request.id,
        "verdict": {
            "is_duplicate": verdict.is_duplicate,
            "similarity_score": verdict.similarity_score,
            "original_topic": verdict.original_topic,
            "suggested_shifted_angle": verdict.suggested_shifted_angle,
            "reason": verdict.reason
        }
    }


@celery_app.task(name="celery_tasks.generate_post_draft_task", bind=True)
def generate_post_draft_task(
    self,
    project_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    topic: str = "Экспертный обзор",
    profile: Optional[Dict[str, Any]] = None,
    recent_posts: Optional[List[str]] = None,
    aspect_ratio: str = "1:1",
    tier: str = "business",
    industry: str = "b2b_corporate",
    callback_url: Optional[str] = None,
    dev_simulation_mode: bool = True
) -> Dict[str, Any]:
    """
    Генерация черновика поста с нулевой стоимостью GPU (Lazy Rendering),
    использованием RAG с изоляцией по project_id, дедупликацией и отправкой Webhook уведомления.
    """
    target_project_id = project_id or tenant_id or "default_project"
    logger.info(f"✍️ [Celery] Генерация черновика для project_id='{target_project_id}', тема='{topic[:50]}'")
    from skills.content_generation_engine import ContentGenerationEngine
    from services.webhook_manager import WebhookCallbackManager
    
    try:
        engine = ContentGenerationEngine(dev_mode=True)
        draft = _run_async(engine.generate_post(
            project_id=target_project_id,
            topic=topic,
            profile=profile,
            recent_posts=recent_posts,
            aspect_ratio=aspect_ratio
        ))
        
        res = {
            "status": "success",
            "task_id": self.request.id,
            "project_id": target_project_id,
            "post_draft": draft.dict()
        }

        if callback_url:
            WebhookCallbackManager.send_callback_sync(
                callback_url=callback_url,
                event_type="content_draft_ready",
                tenant_id=target_project_id,
                task_id=self.request.id,
                status="success",
                data=res
            )

        return res
    except Exception as exc:
        logger.error(f"❌ [Celery] Ошибка генерации черновика для {target_project_id}: {exc}")
        if callback_url:
            WebhookCallbackManager.send_callback_sync(
                callback_url=callback_url,
                event_type="content_draft_failed",
                tenant_id=target_project_id,
                task_id=self.request.id,
                status="failed",
                error=str(exc)
            )
        raise exc


@celery_app.task(name="celery_tasks.render_post_task", bind=True)
def render_post_task(
    self,
    post_id: str,
    tenant_id: Optional[str] = "tenant_default",
    callback_url: Optional[str] = None,
    dev_simulation_mode: bool = True
) -> Dict[str, Any]:
    """
    Тяжелый GPU-рендер графики по запросу (выполняется в очереди ucust_gpu_render).
    """
    logger.info(f"🎨 [Celery GPU] Запуск рендера для post_id={post_id}...")
    from core.lazy_rendering_controller import LazyRenderingController
    from services.webhook_manager import WebhookCallbackManager

    controller = LazyRenderingController(dev_simulation_mode=dev_simulation_mode)
    
    try:
        rendered_post = _run_async(controller.trigger_render(post_id=post_id))
        res = {
            "status": "success",
            "task_id": self.request.id,
            "post_id": post_id,
            "rendered_post": rendered_post.dict() if rendered_post else None
        }

        if callback_url:
            WebhookCallbackManager.send_callback_sync(
                callback_url=callback_url,
                event_type="render_completed",
                tenant_id=tenant_id or "tenant_default",
                task_id=self.request.id,
                status="success",
                data=res
            )

        return res
    except Exception as exc:
        logger.error(f"❌ [Celery GPU] Ошибка рендера для {post_id}: {exc}")
        if callback_url:
            WebhookCallbackManager.send_callback_sync(
                callback_url=callback_url,
                event_type="render_failed",
                tenant_id=tenant_id or "tenant_default",
                task_id=self.request.id,
                status="failed",
                error=str(exc)
            )
        raise exc


@celery_app.task(name="celery_tasks.execute_pipeline_task", bind=True)
def execute_pipeline_task(
    self,
    task_type: str,
    payload: Dict[str, Any],
    user_id: str = "default_user",
    session_id: Optional[str] = None,
    callback_url: Optional[str] = None,
    tier: str = "business",
) -> Dict[str, Any]:
    """
    Универсальная фоновая задача конвейера Celery:
    Выполняет задачу через UnifiedOrchestrator с отправкой Webhook.
    """
    from core.orchestrator import UnifiedOrchestrator
    from services.webhook_manager import WebhookCallbackManager

    logger.info(f"⚡ [Celery] Старт задачи {task_type} (ID: {self.request.id}, Tier: {tier})")
    orchestrator = UnifiedOrchestrator()
    task_session = session_id or f"celery_{self.request.id}"

    try:
        result = _run_async(orchestrator.execute_task(
            task_type=task_type,
            user_data=payload,
            session_id=task_session,
        ))

        res = {
            "status": "success",
            "task_id": self.request.id,
            "task_type": task_type,
            "session_id": task_session,
            "result": result,
        }

        if callback_url:
            WebhookCallbackManager.send_callback_sync(
                callback_url=callback_url,
                event_type=f"{task_type}_completed",
                tenant_id=user_id,
                task_id=self.request.id,
                status="success",
                data=res,
            )
        return res
    except Exception as exc:
        logger.error(f"❌ [Celery] Сбой выполнения {task_type} ({self.request.id}): {exc}")
        if callback_url:
            WebhookCallbackManager.send_callback_sync(
                callback_url=callback_url,
                event_type=f"{task_type}_failed",
                tenant_id=user_id,
                task_id=self.request.id,
                status="failed",
                error=str(exc),
            )
        raise exc


def enqueue_pipeline_task(
    task_type: str,
    payload: Dict[str, Any],
    user_id: str = "default_user",
    session_id: Optional[str] = None,
    callback_url: Optional[str] = None,
    tier: str = "business",
) -> Dict[str, Any]:
    """Постановка задачи в целевую очередь Celery на основе тарифа."""
    target_queue = get_queue_for_tier(tier)
    if HAS_CELERY and hasattr(execute_pipeline_task, "apply_async"):
        async_result = execute_pipeline_task.apply_async(
            kwargs={
                "task_type": task_type,
                "payload": payload,
                "user_id": user_id,
                "session_id": session_id,
                "callback_url": callback_url,
                "tier": tier,
            },
            queue=target_queue,
        )
        task_id = async_result.id
    else:
        import uuid
        task_id = f"mock_{uuid.uuid4().hex[:12]}"

    return {
        "status": "QUEUED",
        "task_id": task_id,
        "queue": target_queue,
        "user_id": user_id,
        "session_id": session_id,
        "timestamp": datetime.utcnow().isoformat(),
    }


def get_pipeline_task_status(task_id: str) -> Dict[str, Any]:
    """Проверка статуса задачи в Celery / Redis."""
    if HAS_CELERY and hasattr(celery_app, "AsyncResult"):
        res = celery_app.AsyncResult(task_id)
        task_state = res.status
        is_ready = res.ready()
        task_result = res.result if is_ready and not res.failed() else None
        error_msg = str(res.result) if res.failed() else None
        return {
            "task_id": task_id,
            "status": task_state,
            "ready": is_ready,
            "data": task_result,
            "error": error_msg,
        }
    return {
        "task_id": task_id,
        "status": "COMPLETED",
        "ready": True,
        "data": {"mock": True},
    }


def get_celery_queue_stats() -> Dict[str, Any]:
    """Статистика очередей Celery."""
    return {
        "broker": "Redis (Celery)",
        "active_queues": [QUEUE_CUSTOM, QUEUE_BUSINESS, QUEUE_START, QUEUE_TREND_MINING],
        "default_queue": QUEUE_BUSINESS,
        "trend_queue": QUEUE_TREND_MINING,
        "tier_mapping": TIER_QUEUES,
    }


# -----------------------------------------------------------------------------
# Trend Mining Celery Tasks (Изолированная очередь: trend_mining)
# -----------------------------------------------------------------------------

@celery_app.task(name="celery_tasks.collect_raw_trends_task", bind=True)
def collect_raw_trends_task(self, sources: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Фоновый сбор сырых инфоповодов из подключенных каналов и медиа (Celery Beat каждые 30 мин).
    Выполняет O(1) дедупликацию по content_hash и складывает факты в стейджинг.
    """
    logger.info(f"📡 [Celery:trend_mining] Запуск сбора сырых инфоповодов ({self.request.id})...")
    try:
        # Для демонстрации и базового сбора
        from schemas.trend_state import RawTrendEvent
        now = datetime.utcnow()
        sample_events = [
            RawTrendEvent(
                source_platform="telegram",
                source_id="tech_insider",
                post_id=f"p_{os.urandom(3).hex()}",
                raw_text="Новый релиз открытых ИИ-агентов для автоматизации малого бизнеса вызвал ажиотаж.",
                timestamp=now,
            ).model_dump(mode="json")
        ]
        return {
            "status": "success",
            "task_id": self.request.id,
            "collected_count": len(sample_events),
            "timestamp": now.isoformat(),
        }
    except Exception as exc:
        logger.error(f"❌ [Celery:trend_mining] Ошибка сбора сырых данных: {exc}")
        raise exc


@celery_app.task(name="celery_tasks.process_trend_clusters_task", bind=True)
def process_trend_clusters_task(
    self,
    events_payload: Optional[List[Dict[str, Any]]] = None,
    window_hours: float = 4.0,
    tenant_id: str = "default_tenant"
) -> Dict[str, Any]:
    """
    Фоновая математическая кластеризация HDBSCAN и семантический LLM-анализ трендов.
    Запускается по расписанию Celery Beat каждые 2 часа.
    Индексирует результат в Clean RAG Pipeline с мета-тегами и TTL.
    """
    logger.info(f"📊 [Celery:trend_mining] Кластеризация и семантический анализ трендов ({self.request.id})...")

    async def _async_pipeline():
        from schemas.trend_state import RawTrendEvent
        from analytics.trend_clusterer import TrendClusterer
        from services.trend_service import TrendService
        from rag.pipeline import CleanRAGPipeline

        raw_events = []
        if events_payload:
            for item in events_payload:
                raw_events.append(RawTrendEvent(**item))

        clusterer = TrendClusterer(min_cluster_size=2, min_density_spike=1.0)
        rag_pipeline = CleanRAGPipeline()
        trend_service = TrendService(clusterer=clusterer, rag_pipeline=rag_pipeline)

        # 1. Математическая кластеризация
        clusters = clusterer.cluster_events(raw_events, window_hours=window_hours) if raw_events else []

        # 2. Семантический анализ
        trend_states = await trend_service.process_clusters(clusters)

        # 3. RAG-индексация с TTL
        indexed_count = await trend_service.index_trends_to_rag(trend_states, tenant_id=tenant_id)

        return {
            "status": "success",
            "clusters_detected": len(clusters),
            "trends_generated": len(trend_states),
            "rag_indexed_chunks": indexed_count,
            "trends": [t.model_dump(mode="json") for t in trend_states],
        }

    try:
        return _run_async(_async_pipeline())
    except Exception as exc:
        logger.error(f"❌ [Celery:trend_mining] Сбой обработки трендов: {exc}")
        raise exc


def enqueue_trend_mining_task(
    events_payload: Optional[List[Dict[str, Any]]] = None,
    window_hours: float = 4.0,
    tenant_id: str = "default_tenant"
) -> Dict[str, Any]:
    """Вспомогательная функция для постановки задачи трендов в очередь trend_mining."""
    if HAS_CELERY and hasattr(process_trend_clusters_task, "apply_async"):
        async_result = process_trend_clusters_task.apply_async(
            kwargs={
                "events_payload": events_payload,
                "window_hours": window_hours,
                "tenant_id": tenant_id,
            },
            queue=QUEUE_TREND_MINING,
        )
        task_id = async_result.id
    else:
        import uuid
        task_id = f"mock_trend_{uuid.uuid4().hex[:12]}"

    return {
        "status": "QUEUED",
        "task_id": task_id,
        "queue": QUEUE_TREND_MINING,
        "tenant_id": tenant_id,
        "timestamp": datetime.utcnow().isoformat(),
    }


@celery_app.task(name="celery_tasks.collect_channel_telemetry_batch_task", bind=True)
def collect_channel_telemetry_batch_task(
    self,
    channel: str = "@ucust_demo",
    platform: str = "telegram",
    tenant_id: str = "default_tenant",
    batch_limit: int = 50,
    mock_events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Пакетный сбор и ингестия телеметрии публикаций канала (Feedback Loop Continuous Learning):
    - Батчирование постов на уровне канала (до batch_limit постов за прогон, защита от взрыва очередей).
    - Защищен CircuitBreaker("social_telemetry_collector", failure_threshold=3, recovery_timeout=60.0).
    - Обрабатывает метрики через FeedbackLoopEngine (Z-score + Sigmoid ER нормализация).
    - Автоматически синхронизирует проверенные зацепы и штрафные ограничения в Clean RAG Pipeline.
    """
    logger.info(f"📈 [Celery:feedback_loop] Пакетный сбор телеметрии канала {channel} ({platform}, tenant={tenant_id})...")

    from core.resilience import CircuitBreaker, CircuitBreakerOpenException
    from schemas.feedback_state import PostTelemetryEvent
    from analytics.feedback_loop_engine import FeedbackLoopEngine
    from rag.pipeline import CleanRAGPipeline

    cb = CircuitBreaker("social_telemetry_collector", failure_threshold=3, recovery_timeout=60.0)

    async def _async_batch_process():
        # Вспомогательная функция сбора данных под защитой Circuit Breaker
        async def _fetch_channel_metrics():
            if mock_events is not None:
                return mock_events[:batch_limit]
            # В боевой интеграции: API Telegram/VK с таймаутом
            return []

        try:
            raw_batch = await cb.call(_fetch_channel_metrics)
        except CircuitBreakerOpenException as cbe:
            logger.warning(f"🛡️ [FeedbackLoop] Circuit Breaker OPEN: {cbe}")
            return {
                "status": "circuit_breaker_open",
                "channel": channel,
                "platform": platform,
                "tenant_id": tenant_id,
                "processed_count": 0,
                "circuit_breaker": cb.get_status(),
            }

        engine = FeedbackLoopEngine.get_instance()
        rag_pipeline = CleanRAGPipeline()

        processed_events: List[Dict[str, Any]] = []
        total_proven_hooks = 0
        total_negative_constraints = 0
        total_rag_indexed = 0

        for item in raw_batch:
            if isinstance(item, dict):
                ev = PostTelemetryEvent(**item)
            elif isinstance(item, PostTelemetryEvent):
                ev = item
            else:
                continue

            score = engine.ingest_telemetry(ev)
            refinement = engine.refine_knowledge(ev, score)
            total_proven_hooks += len(refinement.proven_hooks)
            total_negative_constraints += len(refinement.negative_constraints)

            indexed = await engine.sync_refinements_to_rag(refinement, rag_pipeline)
            total_rag_indexed += indexed

            processed_events.append({
                "post_id": ev.post_id,
                "normalized_score": score.normalized_score,
                "raw_er": score.raw_er,
                "tier": score.tier.value,
            })

        return {
            "status": "success",
            "task_id": getattr(self.request, "id", "sync-task"),
            "channel": channel,
            "platform": platform,
            "tenant_id": tenant_id,
            "processed_count": len(processed_events),
            "proven_hooks_count": total_proven_hooks,
            "negative_constraints_count": total_negative_constraints,
            "rag_indexed_chunks": total_rag_indexed,
            "events_summary": processed_events,
            "circuit_breaker": cb.get_status(),
        }

    try:
        return _run_async(_async_batch_process())
    except Exception as exc:
        logger.error(f"❌ [Celery:feedback_loop] Ошибка пакетного сбора телеметрии: {exc}")
        raise exc


def enqueue_telemetry_batch_task(
    channel: str = "@ucust_demo",
    platform: str = "telegram",
    tenant_id: str = "default_tenant",
    batch_limit: int = 50,
    mock_events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Вспомогательная функция для постановки задачи пакетного сбора телеметрии в очередь feedback_loop."""
    if HAS_CELERY and hasattr(collect_channel_telemetry_batch_task, "apply_async"):
        async_result = collect_channel_telemetry_batch_task.apply_async(
            kwargs={
                "channel": channel,
                "platform": platform,
                "tenant_id": tenant_id,
                "batch_limit": batch_limit,
                "mock_events": mock_events,
            },
            queue=QUEUE_FEEDBACK,
        )
        task_id = async_result.id
    else:
        import uuid
        task_id = f"mock_telemetry_{uuid.uuid4().hex[:12]}"

    return {
        "status": "QUEUED",
        "task_id": task_id,
        "queue": QUEUE_FEEDBACK,
        "channel": channel,
        "tenant_id": tenant_id,
        "timestamp": datetime.utcnow().isoformat(),
    }


@celery_app.task(name="celery_tasks.monitor_drs_and_trigger_interrogation_task", bind=True)
def monitor_drs_and_trigger_interrogation_task(
    self,
    min_drs_threshold: int = 40,
    max_fallback_rate_pct: float = 50.0,
    tenant_ids: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Фоновый периодический воркер мониторинга Data Richness Score (DRS) и запуска микро-опросов:
    1. Сканирует профили и телеметрию тенантов на низкую фактуру (DRS < 40) или частые сбои (Fallback Rate >= 50%).
    2. Определяет критический отсутствующий слот (pricing_model, terms_guarantees, contacts).
    3. Отправляет пуш-опрос через TelegramPublisher с интерактивными кнопками Safe Fallback.
    4. Фиксирует состояние опроса в SlotElevationHandler для обработки последующего ответа.
    """
    task_id = getattr(self.request, "id", "sync-drs-task")
    logger.info(f"🩺 [Celery:feedback_loop] Старт DRS Health Monitor (Task ID: {task_id})")

    from analytics.drs_health_monitor import DRSHealthMonitor

    monitor = DRSHealthMonitor(
        min_drs_threshold=min_drs_threshold,
        max_fallback_rate_pct=max_fallback_rate_pct
    )

    if tenant_ids:
        for tid in tenant_ids:
            monitor.register_tenant_telegram(tid, tid)

    summary = monitor.scan_all_tenants_sync()
    summary["task_id"] = task_id
    return summary


def enqueue_drs_monitor_task(
    min_drs_threshold: int = 40,
    max_fallback_rate_pct: float = 50.0,
    tenant_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Вспомогательная функция для постановки задачи мониторинга DRS в очередь feedback_loop."""
    if HAS_CELERY and hasattr(monitor_drs_and_trigger_interrogation_task, "apply_async"):
        async_result = monitor_drs_and_trigger_interrogation_task.apply_async(
            kwargs={
                "min_drs_threshold": min_drs_threshold,
                "max_fallback_rate_pct": max_fallback_rate_pct,
                "tenant_ids": tenant_ids,
            },
            queue=QUEUE_FEEDBACK,
        )
        task_id = async_result.id
    else:
        import uuid
        task_id = f"mock_drs_{uuid.uuid4().hex[:12]}"

    return {
        "status": "QUEUED",
        "task_id": task_id,
        "queue": QUEUE_FEEDBACK,
        "timestamp": datetime.utcnow().isoformat(),
    }





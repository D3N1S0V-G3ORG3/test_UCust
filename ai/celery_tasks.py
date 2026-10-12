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

# Названия очередей по приоритету тарифов
QUEUE_START = "start"          # Старт (базовый тариф)
QUEUE_BUSINESS = "business"    # Бизнес (коммерческий тариф)
QUEUE_CUSTOM = "custom"        # Свой тариф / Кастомный (VIP)

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
            "celery_tasks.*": {"queue": QUEUE_BUSINESS},
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
        "active_queues": [QUEUE_CUSTOM, QUEUE_BUSINESS, QUEUE_START],
        "default_queue": QUEUE_BUSINESS,
        "tier_mapping": TIER_QUEUES,
    }


"""
File: ai/api/routers/async_tasks.py
FastAPI маршрутизатор асинхронных очередей Celery.
"""

from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, status

try:
    from models.api_models import (
        OnboardingAsyncRequest,
        ContentGenerateAsyncRequest,
        AsyncTaskAcceptedResponse
    )
    from api.dependencies.auth import get_current_tenant
    from celery_tasks import celery_app, get_queue_for_tier, QUEUE_BUSINESS
except ImportError:
    from ai.models.api_models import (
        OnboardingAsyncRequest,
        ContentGenerateAsyncRequest,
        AsyncTaskAcceptedResponse
    )
    from ai.api.dependencies.auth import get_current_tenant
    from ai.celery_tasks import celery_app, get_queue_for_tier, QUEUE_BUSINESS

logger = logging.getLogger("AsyncTasksRouter")

router = APIRouter(prefix="/api/v1", tags=["Async Tasks Queue"])


@router.post(
    "/onboarding/async",
    response_model=AsyncTaskAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Асинхронный запуск онбординга бренда"
)
async def trigger_onboarding_task(
    request: OnboardingAsyncRequest,
    tenant_id: str = Depends(get_current_tenant)
):
    """
    Асинхронный сбор данных (Telegram, Website, PDF) и извлечение Brand DNA.
    Задача отправляется в очередь соответствующего тарифа (start / business / custom).
    """
    payload_dict = request.model_dump(mode="json")
    target_queue = get_queue_for_tier(payload_dict.get("tier", "business"))
    
    task = celery_app.send_task(
        "celery_tasks.onboard_brand_task",
        kwargs={
            "tenant_id": tenant_id,
            "company_name": payload_dict.get("company_name"),
            "niche": payload_dict.get("niche"),
            "telegram_channel": payload_dict.get("telegram_channel"),
            "website_url": payload_dict.get("website_url"),
            "document_paths": payload_dict.get("document_paths"),
            "raw_notes": payload_dict.get("raw_notes"),
            "callback_url": payload_dict.get("callback_url")
        },
        queue=target_queue
    )
    
    logger.info(f"📤 [Router] Задача онбординга поставлена в очередь '{target_queue}' (task_id={task.id}, tenant={tenant_id})")
    
    return AsyncTaskAcceptedResponse(
        task_id=task.id,
        tenant_id=tenant_id,
        queue_name=target_queue,
        estimated_wait_seconds=15.0
    )


@router.post(
    "/content/generate-async",
    response_model=AsyncTaskAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Асинхронный запуск генерации контента (Lazy Rendering)"
)
async def trigger_content_generation_task(
    request: ContentGenerateAsyncRequest,
    tenant_id: str = Depends(get_current_tenant)
):
    """
    Асинхронная генерация контент-плана или черновика поста с нулевой стоимостью GPU.
    Задача отправляется в очередь соответствующего тарифа (start / business / custom).
    """
    payload_dict = request.model_dump(mode="json")
    tier_val = payload_dict.get("tier", "business")
    target_queue = get_queue_for_tier(tier_val)
    
    task = celery_app.send_task(
        "celery_tasks.generate_post_draft_task",
        kwargs={
            "tenant_id": tenant_id,
            "tier": tier_val,
            "industry": payload_dict.get("industry", "b2b_corporate"),
            "topic": payload_dict.get("prompt", "Обзор"),
            "callback_url": payload_dict.get("callback_url")
        },
        queue=target_queue
    )
    
    logger.info(f"📤 [Router] Задача генерации поставлена в очередь '{target_queue}' (task_id={task.id}, tenant={tenant_id})")
    
    return AsyncTaskAcceptedResponse(
        task_id=task.id,
        tenant_id=tenant_id,
        queue_name=target_queue,
        estimated_wait_seconds=2.5
    )

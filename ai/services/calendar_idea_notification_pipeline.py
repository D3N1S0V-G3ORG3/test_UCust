"""
File: ai/services/calendar_idea_notification_pipeline.py
Пайплайн асинхронных уведомлений и вебхуков для Календаря контента,
Ленивого GPU-Рендера, Умного Банка Идей и Шлюза согласования акций.
"""

from __future__ import annotations

import os
import time
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from services.webhook_manager import WebhookCallbackManager

logger = logging.getLogger("CalendarIdeaNotificationPipeline")


# ============================================================================
# 1. Pydantic Модели событий (Event Schemas)
# ============================================================================

class CalendarGridGeneratedEvent(BaseModel):
    project_id: str
    tenant_id: str = "dev"
    days_count: int
    start_date: str
    end_date: str
    posts_count: int
    funnel_split: Dict[str, float] = Field(default_factory=lambda: {"tofu": 0.4, "mofu": 0.4, "bofu": 0.2})
    posts_summary: List[Dict[str, Any]] = Field(default_factory=list)


class SlotScheduledEvent(BaseModel):
    project_id: str
    tenant_id: str = "dev"
    post_id: str
    publish_at: str
    funnel_stage: str
    post_format: str
    topic: str
    critic_score: float = 0.95
    is_promo: bool = False


class RenderLazyQueuedEvent(BaseModel):
    project_id: str
    tenant_id: str = "dev"
    post_id: str
    render_task_id: str
    shot_intent: str = "product_only"
    aspect_ratio: str = "1:1"
    vram_cost_mb: int = 4200
    estimated_time_sec: int = 8


class RenderCompletedEvent(BaseModel):
    project_id: str
    tenant_id: str = "dev"
    post_id: str
    render_task_id: str
    rendered_image_urls: List[str]
    render_time_sec: float
    vram_peak_mb: int = 4200


class IdeaRadarSyncedEvent(BaseModel):
    tenant_id: str = "dev"
    niche: str
    country: str = "россия"
    city: str = "Москва"
    horizon_days: int = 21
    events_count: int
    upcoming_events: List[Dict[str, Any]] = Field(default_factory=list)


class TabPlaceholderSuggestedEvent(BaseModel):
    tenant_id: str = "dev"
    niche: str
    placeholder_text: str
    suggested_topic: str
    funnel_stage: str
    trigger_type: str = "calendar"


class FunnelSlotConflictWarningEvent(BaseModel):
    tenant_id: str = "dev"
    project_id: str
    topic: str
    requested_slot: str
    recommended_slot: str
    warning_explanation: str
    suggested_alternatives: List[str] = Field(default_factory=list)


class PromoApprovalRequiredEvent(BaseModel):
    """Событие жесткого шлюза безопасности: акция требует подтверждения человека."""
    tenant_id: str = "dev"
    project_id: str
    post_id: str
    product_name: str
    discount_text: str
    promo_code: Optional[str] = None
    old_price: Optional[str] = None
    new_price: Optional[str] = None
    expires_at: Optional[str] = None
    margin_impact: Optional[str] = None
    post_preview_html: str
    approval_token: str


class PromoDecisionRecordedEvent(BaseModel):
    tenant_id: str = "dev"
    project_id: str
    post_id: str
    decision: str  # approved | rejected | modified
    user_id: str
    scheduled_publish_at: Optional[str] = None


# ============================================================================
# 2. Менеджер пайплайна уведомлений (Pipeline Dispatcher)
# ============================================================================

class CalendarIdeaNotificationPipeline:
    """
    Высокоуровневый фасад диспетчеризации событий в бэкенд:
    1. Календарь и Lazy GPU рендер
    2. Умный Банк Идей и Радар инфоповодов
    3. Жесткий шлюз согласования акций (Human-in-the-Loop)
    """

    DEFAULT_BACKEND_WEBHOOK_URL = os.getenv(
        "BACKEND_WEBHOOK_URL",
        "http://localhost:8080/api/v1/ai/webhook"
    )

    # ------------------------------------------------------------------------
    # Пункт 2: Календарное планирование & Lazy GPU Lifecycle
    # ------------------------------------------------------------------------

    @classmethod
    async def emit_calendar_grid_generated(
        cls,
        project_id: str,
        posts_count: int,
        start_date: str,
        end_date: str,
        posts_summary: List[Dict[str, Any]],
        funnel_split: Optional[Dict[str, float]] = None,
        tenant_id: str = "dev",
        callback_url: Optional[str] = None
    ) -> bool:
        """Уведомление: Сгенерирована новая сетка контент-плана (0 GPU)."""
        url = callback_url or cls.DEFAULT_BACKEND_WEBHOOK_URL
        event_data = CalendarGridGeneratedEvent(
            project_id=project_id,
            tenant_id=tenant_id,
            days_count=len(posts_summary),
            start_date=start_date,
            end_date=end_date,
            posts_count=posts_count,
            funnel_split=funnel_split or {"tofu": 0.4, "mofu": 0.4, "bofu": 0.2},
            posts_summary=posts_summary
        ).model_dump()

        return await WebhookCallbackManager.send_callback_async(
            callback_url=url,
            event_type="calendar.grid_generated",
            tenant_id=tenant_id,
            task_id=f"cal_grid_{uuid.uuid4().hex[:8]}",
            status="completed",
            data=event_data
        )

    @classmethod
    async def emit_slot_scheduled(
        cls,
        project_id: str,
        post_id: str,
        publish_at: str,
        funnel_stage: str,
        post_format: str,
        topic: str,
        critic_score: float = 0.95,
        is_promo: bool = False,
        tenant_id: str = "dev",
        callback_url: Optional[str] = None
    ) -> bool:
        """Уведомление: Слот в календаре зафиксирован и назначен."""
        url = callback_url or cls.DEFAULT_BACKEND_WEBHOOK_URL
        event_data = SlotScheduledEvent(
            project_id=project_id,
            tenant_id=tenant_id,
            post_id=post_id,
            publish_at=publish_at,
            funnel_stage=funnel_stage,
            post_format=post_format,
            topic=topic,
            critic_score=critic_score,
            is_promo=is_promo
        ).model_dump()

        return await WebhookCallbackManager.send_callback_async(
            callback_url=url,
            event_type="calendar.slot_scheduled",
            tenant_id=tenant_id,
            task_id=f"slot_{post_id}",
            status="scheduled",
            data=event_data
        )

    @classmethod
    async def emit_render_queued(
        cls,
        project_id: str,
        post_id: str,
        render_task_id: str,
        shot_intent: str = "product_only",
        aspect_ratio: str = "1:1",
        vram_cost_mb: int = 4200,
        tenant_id: str = "dev",
        callback_url: Optional[str] = None
    ) -> bool:
        """Уведомление: Отложенный рендер поставлен в очередь ComfyUI (Just-in-Time)."""
        url = callback_url or cls.DEFAULT_BACKEND_WEBHOOK_URL
        event_data = RenderLazyQueuedEvent(
            project_id=project_id,
            tenant_id=tenant_id,
            post_id=post_id,
            render_task_id=render_task_id,
            shot_intent=shot_intent,
            aspect_ratio=aspect_ratio,
            vram_cost_mb=vram_cost_mb,
            estimated_time_sec=8
        ).model_dump()

        return await WebhookCallbackManager.send_callback_async(
            callback_url=url,
            event_type="render.lazy_queued",
            tenant_id=tenant_id,
            task_id=render_task_id,
            status="rendering",
            data=event_data
        )

    @classmethod
    async def emit_render_completed(
        cls,
        project_id: str,
        post_id: str,
        render_task_id: str,
        rendered_image_urls: List[str],
        render_time_sec: float,
        tenant_id: str = "dev",
        callback_url: Optional[str] = None
    ) -> bool:
        """Уведомление: Рендер изображений завершен, пост готов к публикации."""
        url = callback_url or cls.DEFAULT_BACKEND_WEBHOOK_URL
        event_data = RenderCompletedEvent(
            project_id=project_id,
            tenant_id=tenant_id,
            post_id=post_id,
            render_task_id=render_task_id,
            rendered_image_urls=rendered_image_urls,
            render_time_sec=render_time_sec,
            vram_peak_mb=4200
        ).model_dump()

        return await WebhookCallbackManager.send_callback_async(
            callback_url=url,
            event_type="render.completed",
            tenant_id=tenant_id,
            task_id=render_task_id,
            status="ready",
            data=event_data
        )

    # ------------------------------------------------------------------------
    # Пункт 3: Умный Банк Идей и Ситуативный Радар
    # ------------------------------------------------------------------------

    @classmethod
    async def emit_idea_radar_synced(
        cls,
        niche: str,
        upcoming_events: List[Dict[str, Any]],
        country: str = "россия",
        city: str = "Москва",
        horizon_days: int = 21,
        tenant_id: str = "dev",
        callback_url: Optional[str] = None
    ) -> bool:
        """Уведомление: Обновлен радар инфоповодов и праздников на 21 день вперед."""
        url = callback_url or cls.DEFAULT_BACKEND_WEBHOOK_URL
        event_data = IdeaRadarSyncedEvent(
            tenant_id=tenant_id,
            niche=niche,
            country=country,
            city=city,
            horizon_days=horizon_days,
            events_count=len(upcoming_events),
            upcoming_events=upcoming_events
        ).model_dump()

        return await WebhookCallbackManager.send_callback_async(
            callback_url=url,
            event_type="ideas.radar_synced",
            tenant_id=tenant_id,
            task_id=f"radar_{uuid.uuid4().hex[:8]}",
            status="synced",
            data=event_data
        )

    @classmethod
    async def emit_tab_placeholder_suggested(
        cls,
        niche: str,
        placeholder_text: str,
        suggested_topic: str,
        funnel_stage: str = "TOFU",
        tenant_id: str = "dev",
        callback_url: Optional[str] = None
    ) -> bool:
        """Уведомление: Сгенерирована актуальная подсказка для поля ввода по Tab."""
        url = callback_url or cls.DEFAULT_BACKEND_WEBHOOK_URL
        event_data = TabPlaceholderSuggestedEvent(
            tenant_id=tenant_id,
            niche=niche,
            placeholder_text=placeholder_text,
            suggested_topic=suggested_topic,
            funnel_stage=funnel_stage
        ).model_dump()

        return await WebhookCallbackManager.send_callback_async(
            callback_url=url,
            event_type="ideas.placeholder_suggested",
            tenant_id=tenant_id,
            task_id=f"tab_{uuid.uuid4().hex[:8]}",
            status="suggested",
            data=event_data
        )

    @classmethod
    async def emit_funnel_slot_conflict(
        cls,
        project_id: str,
        topic: str,
        requested_slot: str,
        recommended_slot: str,
        warning_explanation: str,
        suggested_alternatives: List[str],
        tenant_id: str = "dev",
        callback_url: Optional[str] = None
    ) -> bool:
        """Уведомление: Зафиксирован риск поломки воронки при размещении темы."""
        url = callback_url or cls.DEFAULT_BACKEND_WEBHOOK_URL
        event_data = FunnelSlotConflictWarningEvent(
            tenant_id=tenant_id,
            project_id=project_id,
            topic=topic,
            requested_slot=requested_slot,
            recommended_slot=recommended_slot,
            warning_explanation=warning_explanation,
            suggested_alternatives=suggested_alternatives
        ).model_dump()

        return await WebhookCallbackManager.send_callback_async(
            callback_url=url,
            event_type="ideas.slot_conflict_warning",
            tenant_id=tenant_id,
            task_id=f"conflict_{uuid.uuid4().hex[:8]}",
            status="warning",
            data=event_data
        )

    # ------------------------------------------------------------------------
    # Пункт 4: Шлюз согласования акций (Human-in-the-Loop Hard-Gate)
    # ------------------------------------------------------------------------

    @classmethod
    async def emit_promo_approval_required(
        cls,
        project_id: str,
        post_id: str,
        product_name: str,
        discount_text: str,
        post_preview_html: str,
        promo_code: Optional[str] = None,
        old_price: Optional[str] = None,
        new_price: Optional[str] = None,
        expires_at: Optional[str] = None,
        margin_impact: Optional[str] = None,
        tenant_id: str = "dev",
        callback_url: Optional[str] = None
    ) -> str:
        """
        Уведомление: Обнаружен промо-пост со скидкой.
        Публикация жестко заблокирована до явного подтверждения человека!
        Возвращает approval_token.
        """
        approval_token = f"appr_tok_{uuid.uuid4().hex}"
        url = callback_url or cls.DEFAULT_BACKEND_WEBHOOK_URL

        event_data = PromoApprovalRequiredEvent(
            tenant_id=tenant_id,
            project_id=project_id,
            post_id=post_id,
            product_name=product_name,
            discount_text=discount_text,
            promo_code=promo_code,
            old_price=old_price,
            new_price=new_price,
            expires_at=expires_at,
            margin_impact=margin_impact or "В пределах нормы",
            post_preview_html=post_preview_html,
            approval_token=approval_token
        ).model_dump()

        await WebhookCallbackManager.send_callback_async(
            callback_url=url,
            event_type="promo.approval_required",
            tenant_id=tenant_id,
            task_id=f"promo_req_{post_id}",
            status="pending_approval",
            data=event_data
        )
        return approval_token

    @classmethod
    async def emit_promo_decision(
        cls,
        project_id: str,
        post_id: str,
        decision: str,  # approved | rejected | modified
        user_id: str,
        scheduled_publish_at: Optional[str] = None,
        tenant_id: str = "dev",
        callback_url: Optional[str] = None
    ) -> bool:
        """Уведомление: Человек принял решение по акции (Утверждено / Отклонено)."""
        url = callback_url or cls.DEFAULT_BACKEND_WEBHOOK_URL
        event_data = PromoDecisionRecordedEvent(
            tenant_id=tenant_id,
            project_id=project_id,
            post_id=post_id,
            decision=decision,
            user_id=user_id,
            scheduled_publish_at=scheduled_publish_at
        ).model_dump()

        return await WebhookCallbackManager.send_callback_async(
            callback_url=url,
            event_type="promo.decision_recorded",
            tenant_id=tenant_id,
            task_id=f"promo_dec_{post_id}",
            status="processed",
            data=event_data
        )


__all__ = [
    "CalendarGridGeneratedEvent",
    "SlotScheduledEvent",
    "RenderLazyQueuedEvent",
    "RenderCompletedEvent",
    "IdeaRadarSyncedEvent",
    "TabPlaceholderSuggestedEvent",
    "FunnelSlotConflictWarningEvent",
    "PromoApprovalRequiredEvent",
    "PromoDecisionRecordedEvent",
    "CalendarIdeaNotificationPipeline"
]

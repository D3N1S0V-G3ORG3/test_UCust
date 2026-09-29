"""
File: ai/models/api_models.py
Pydantic v2 модели запросов и ответов для асинхронных точек входа.
"""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field, HttpUrl
from core.lazy_rendering_controller import SubscriptionTier, IndustryArchetype


class OnboardingAsyncRequest(BaseModel):
    """Схема запроса на асинхронный онбординг бренда."""
    company_name: str = Field(..., min_length=2, max_length=100, description="Название компании/бренда")
    niche: str = Field(..., min_length=2, max_length=100, description="Ниша или сфера деятельности")
    telegram_channel: Optional[str] = Field(None, description="Username или ссылка на Telegram канал")
    website_url: Optional[HttpUrl] = Field(None, description="URL сайта компании")
    document_paths: Optional[List[str]] = Field(default_factory=list, description="Пути к загруженным документам")
    raw_notes: Optional[str] = Field(None, description="Дополнительные заметки и вводные")
    tier: SubscriptionTier = Field(default=SubscriptionTier.BUSINESS, description="Тарифный план (start/business/custom)")
    callback_url: Optional[HttpUrl] = Field(None, description="URL для Webhook Push по завершении")


class ContentGenerateAsyncRequest(BaseModel):
    """Схема запроса на асинхронную генерацию контента."""
    prompt: str = Field(..., min_length=3, description="Тема или промпт для генерации")
    tier: SubscriptionTier = Field(default=SubscriptionTier.BUSINESS, description="Тарифный план (start/business/custom)")
    industry: IndustryArchetype = Field(default=IndustryArchetype.B2B_CORPORATE, description="Архетип индустрии")
    rubric: Optional[str] = Field(default="general", description="Рубрика поста")
    callback_url: Optional[HttpUrl] = Field(None, description="URL для Webhook Push по завершении")


class AsyncTaskAcceptedResponse(BaseModel):
    """Схема синхронного ответа при постановке в очередь (202 Accepted)."""
    status: str = "accepted"
    task_id: str
    tenant_id: str
    queue_name: str
    estimated_wait_seconds: float = 1.5

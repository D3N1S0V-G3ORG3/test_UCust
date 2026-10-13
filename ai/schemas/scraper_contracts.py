"""
File: ai/schemas/scraper_contracts.py
Строгие Pydantic v2 контракты интеграции между CampaignService (UCust AI Core)
и Background Scraper Backend (Hybrid RAG + JIT Fallback Architecture).
"""

from __future__ import annotations

import re
import hashlib
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ScrapeFrequencyEnum(str, Enum):
    TWICE_DAILY = "twice_daily"   # Основной режим (06:00 и 15:00 UTC)
    HOURLY = "hourly"             # Экспресс-мониторинг для критичных ниш
    DAILY = "daily"               # Эконом-режим (06:00 UTC)


class SourceTypeEnum(str, Enum):
    TELEGRAM = "telegram"
    RSS = "rss"
    NEWSCATCHER = "newscatcher"
    TAVILY = "tavily"
    VK = "vk"
    WEB_MEDIA = "web_media"


class KnowledgeScopeEnum(str, Enum):
    GLOBAL = "global"                   # Публичные городские и отраслевые факты (видны всем кофейням/пекарням)
    TENANT_PRIVATE = "tenant_private"   # Приватные данные и закрытые инсайды конкретного бренда


class KnowledgeTypeEnum(str, Enum):
    BACKGROUND_NEWS = "background_news" # Фоновый сбор по расписанию
    JIT_CACHE = "jit_cache"             # Кэш после RAG Miss через JIT-поиск
    TREND_AGENDA = "trend_agenda"       # Кластеризованный макро/микро тренд


class SourceFeedConfig(BaseModel):
    """Конфигурация отдельного новостного источника тенанта."""
    source_type: SourceTypeEnum = Field(..., description="Тип парсера: telegram, rss, newscatcher и т.д.")
    endpoint_or_url: str = Field(..., description="URL RSS-ленты, username Telegram-канала или ID сообщества")
    category: str = Field(default="general", description="Категория: city_news, logistics, niche_trends, weather")
    weight: float = Field(default=1.0, ge=0.1, le=2.0, description="Вес достоверности источника")


class TenantInterestWebhookRequest(BaseModel):
    """
    Webhook запрос от основного бэкенда при онбординге или обновлении профиля бренда.
    Передает фоновому скрейперу скоуп интересов для периодического сбора.
    """
    tenant_id: str = Field(..., description="Уникальный ID тенанта")
    city: str = Field(..., description="Город присутствия бизнеса (например, 'Москва')")
    niche: str = Field(..., description="Основная сфера деятельности (например, 'кофейня')")
    sub_niches: List[str] = Field(
        default_factory=list,
        description="Узкие специализации (например: ['спешелти кофе', 'обжарка зерна', 'b2b поставки'])"
    )
    keywords: List[str] = Field(
        default_factory=list,
        description="Ключевые слова мониторинга (например: ['логистика зерна', 'таможенные пошлины', 'Колумбия'])"
    )
    custom_sources: List[SourceFeedConfig] = Field(
        default_factory=list,
        description="Специфичные Telegram-каналы или RSS-ленты, запрошенные клиентом"
    )
    frequency: ScrapeFrequencyEnum = Field(
        default=ScrapeFrequencyEnum.TWICE_DAILY,
        description="Периодичность сбора (по умолчанию 2 раза в день)"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TenantInterestWebhookResponse(BaseModel):
    """Подтверждение регистрации интересов от Background Scraper Backend."""
    status: str = Field(default="registered", description="registered | updated | acknowledged")
    tenant_id: str = Field(...)
    active_crawler_jobs: List[str] = Field(default_factory=list, description="Идентификаторы созданных задач скрейпинга")
    next_scheduled_run: Optional[str] = Field(None, description="ISO 8601 время следующего запуска краулеров")
    registered_at: datetime = Field(default_factory=datetime.utcnow)


class BackgroundNewsMetadata(BaseModel):
    """Метаданные факта, сохраняемого в векторную БД (RAG)."""
    type: KnowledgeTypeEnum = Field(default=KnowledgeTypeEnum.BACKGROUND_NEWS)
    scope: KnowledgeScopeEnum = Field(default=KnowledgeScopeEnum.GLOBAL)
    tenant_id: str = Field(default="global", description="'global' для общих фактов или конкретный tenant_id")
    city: str = Field(...)
    niche: str = Field(...)
    category: str = Field(..., description="logistics | weather | city_events | niche_trends | market")
    source_platform: SourceTypeEnum = Field(...)
    source_url: Optional[str] = Field(None)
    date: str = Field(..., description="Формат YYYY-MM-DD для быстрого партиционирования")
    created_at: str = Field(..., description="ISO 8601 метка времени добавления")
    ttl_hours: float = Field(default=48.0, description="Время жизни: 48h для погоды/событий, 336h (14 дней) для логистики")
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)


class BackgroundNewsDocument(BaseModel):
    """Контракт документа для индексации в векторную БД (CleanRAG / Qdrant)."""
    doc_id: str = Field(..., description="Уникальный ID документа: bnews_{city}_{niche}_{hash[:8]}")
    title: str = Field(..., description="Краткий емкий заголовок факта")
    text: str = Field(..., description="Очищенный, суммаризированный текст факта для эмбеддинга")
    embedding: Optional[List[float]] = Field(None, description="Вектор размерности 384 или 1536 (если векторизован на парсере)")
    metadata: BackgroundNewsMetadata = Field(...)


class JITCacheIngestRequest(BaseModel):
    """
    Контракт асинхронного пополнения RAG-базы после срабатывания JIT Fallback (эффект снежного кома).
    """
    query: str = Field(..., description="Исходный поисковый запрос, вызвавший RAG Miss")
    city: str = Field(...)
    niche: str = Field(...)
    fact_text: str = Field(..., description="Свеженайденный факт из Tavily / Apify")
    source: SourceTypeEnum = Field(default=SourceTypeEnum.TAVILY)
    scope: KnowledgeScopeEnum = Field(default=KnowledgeScopeEnum.GLOBAL)
    tenant_id: str = Field(default="global")
    ttl_hours: float = Field(default=48.0, description="Срок жизни в кэше")
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)


class SingleflightLockProtocol:
    """Утилита формирования ключей и каналов для защиты от давки кэша (Cache Stampede Mutex)."""

    @staticmethod
    def normalize_query_key(text: str) -> str:
        clean = re.sub(r"[^\w\s]", "", text.lower())
        clean = re.sub(r"\s+", " ", clean).strip()
        return hashlib.md5(clean.encode("utf-8")).hexdigest()[:12]

    @classmethod
    def make_lock_key(cls, city: str, niche: str, query: str) -> str:
        q_hash = cls.normalize_query_key(query)
        return f"jit_lock:{city.lower()}:{niche.lower()}:{q_hash}"

    @classmethod
    def make_pubsub_channel(cls, city: str, niche: str, query: str) -> str:
        q_hash = cls.normalize_query_key(query)
        return f"jit_channel:{city.lower()}:{niche.lower()}:{q_hash}"

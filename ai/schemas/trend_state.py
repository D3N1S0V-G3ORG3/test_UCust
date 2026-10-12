"""
File: ai/schemas/trend_state.py
Строгие Pydantic v2 контракты для конвейера Trend Mining & Intelligence.
Обеспечивают дедупликацию, изоляцию математического слоя кластеризации
и безопасную передачу контекста в семантический слой без риска Context Bloat.
"""

from __future__ import annotations

import re
import hashlib
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class TrendLifecycleEnum(str, Enum):
    MICRO_HYPE = "micro_hype"       # Всплеск на 24-48 часов (вирусный инфоповод)
    MACRO_TREND = "macro_trend"     # Долгосрочный структурный сдвиг (недели/месяцы)
    STABLE_NICHE = "stable_niche"   # Фоновый интерес внутри определенной ниши


class TrendSentimentEnum(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class RawTrendEvent(BaseModel):
    """
    Минимальный сырой факт со слоя сбора данных (Collectors Layer).
    Содержит криптографический нормализованный хэш для O(1) дедупликации в Redis/кэше.
    """
    source_platform: str = Field(..., description="telegram | vk | rss | web_media")
    source_id: str = Field(..., description="ID или username источника (канал/группа/домен)")
    post_id: str = Field(..., description="ID оригинального сообщения/статьи на платформе")
    raw_text: str = Field(..., description="Сырой исходный текст публикации")
    author_id: Optional[str] = Field(None, description="Автор или идентификатор канала")
    media_links: List[str] = Field(default_factory=list, description="Ссылки на прикрепленные изображения или видео")
    engagement_metrics: Dict[str, Any] = Field(
        default_factory=dict,
        description="Метрики вовлеченности: views, forwards, likes, comments"
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Время публикации")
    content_hash: str = Field(default="", description="Нормализованный SHA-256 хэш")

    @classmethod
    def calculate_normalized_hash(cls, text: str, source_id: str) -> str:
        """
        Генерирует SHA-256 хэш поверх нормализованного текста (без пунктуации, url, пробелов и регистра)
        в связке с source_id для предотвращения коллизий и отсечения дублей.
        """
        # Удаляем URL
        clean = re.sub(r"https?://\S+|www\.\S+", "", text.lower())
        # Удаляем спецсимволы и пунктуацию
        clean = re.sub(r"[^\w\s]", "", clean, flags=re.UNICODE)
        # Схлопываем пробелы
        clean = re.sub(r"\s+", " ", clean).strip()
        payload = f"{source_id}:{clean}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def model_post_init(self, __context: Any) -> None:
        """Автоматическое вычисление content_hash, если не был передан явно."""
        if not self.content_hash:
            self.content_hash = self.calculate_normalized_hash(self.raw_text, self.source_id)


class TrendCluster(BaseModel):
    """
    Математический кластер данных (Clustering Layer).
    Формируется алгоритмом плотностной кластеризации (HDBSCAN / DBSCAN).
    Содержит строго ограниченный массив репрезентативных текстов центроида для защиты VRAM.
    """
    cluster_id: str = Field(..., description="Уникальный идентификатор выявленного кластера")
    total_samples: int = Field(..., description="Количество сообщений, вошедших в кластер")
    velocity_score: float = Field(..., description="Скорость нарастания упоминаний (сообщений в час)")
    density_spike: float = Field(..., description="Кратность аномального прироста к базовой линии (например, 3.5x)")
    cluster_centroid_vector: Optional[List[float]] = Field(None, description="Координаты центроида в эмбеддинг-пространстве")
    centroid_representative_texts: List[str] = Field(
        ...,
        max_length=10,
        description="Топ 5-10 ближайших к центроиду текстов (жестко ограничено для предотвращения OOM)"
    )
    total_representative_tokens: int = Field(default=0, description="Суммарная длина токенов центроида")
    media_samples: List[str] = Field(default_factory=list, description="Выборка вирусных медиа для VLM анализа")
    timespan_hours: float = Field(default=4.0, description="Временное окно анализа в часах")
    detected_at: datetime = Field(default_factory=datetime.utcnow)


class TrendState(BaseModel):
    """
    Финальный верифицированный контракт тренда (Semantic Agent Layer).
    Готов для сохранения в БД, отправки в Grafana Loki и обогащения CampaignService через RAG.
    """
    trend_id: str = Field(..., description="Уникальный идентификатор тренда")
    cluster_id: str = Field(..., description="ID исходного математического кластера")
    topic_headline: str = Field(..., description="Суть инфоповода в 1 предложении (сгенерировано Saiga LLM)")
    summary: str = Field(..., description="Развернутое аналитическое резюме инфоповода")
    niche_categories: List[str] = Field(default_factory=list, description="Тематические ниши (IT, Retail, Finance и т.д.)")
    trend_lifecycle: TrendLifecycleEnum = Field(default=TrendLifecycleEnum.MICRO_HYPE)
    sentiment: TrendSentimentEnum = Field(default=TrendSentimentEnum.NEUTRAL)
    key_entities: List[str] = Field(default_factory=list, description="Ключевые действующие лица, бренды, технологии")
    relevance_score: float = Field(..., ge=0.0, le=1.0, description="Оценка релевантности для коммерческого маркетинга (0-1)")
    source_references: List[str] = Field(default_factory=list, description="Ссылки на первоисточники инфоповода")
    velocity_growth_rate: float = Field(default=1.0, description="Математическая скорость роста тренда")
    tokens_consumed: int = Field(default=0, description="Потребление токенов при семантическом анализе")
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)
    is_actionable: bool = Field(default=True, description="Пригоден ли тренд для генерации рекламного контента")

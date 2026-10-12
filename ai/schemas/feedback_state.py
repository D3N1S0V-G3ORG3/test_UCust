"""
File: ai/schemas/feedback_state.py
Строгие типизированные Pydantic v2 контракты слоя Ingestion и петли обратной связи (Feedback Loop):
1. PostTelemetryEvent — сырой контракт телеметрии публикаций (Telegram, VK).
2. TelemetryMetrics — структурированные метрики вовлечения (показы, репосты, лайки, сохранения, комментарии).
3. GenerationMetadataLink — жесткая связка телеметрии со сквозным PipelineState (промпт, формат, триггеры Мангера).
4. EngagementScore — нормализованная оценка эффективности относительно базовой линии (Baseline) тенанта.
5. TenantBaseline — статистическая базовая линия тенанта/канала (Mean, Median, StdDev, Risky Formats).
6. FeedbackKnowledgeRefinement — контракт для Append-Only обогащения RAG (proven_hooks & negative_constraints).
"""

from __future__ import annotations

import os
import time
from enum import Enum
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class PerformanceTierEnum(str, Enum):
    STELLAR = "stellar"                    # Top > 85% (Score >= 0.85)
    ABOVE_AVERAGE = "above_average"        # 60% - 85% (Score 0.60 - 0.84)
    AVERAGE = "average"                    # 40% - 60% (Score 0.40 - 0.59)
    UNDERPERFORMING = "underperforming"    # 20% - 40% (Score 0.20 - 0.39)
    CRITICAL_FAIL = "critical_fail"        # < 20% (Score < 0.20)


class TelemetryMetrics(BaseModel):
    """Структурированные сырые метрики реакции аудитории."""
    views: int = Field(default=0, ge=0, description="Количество просмотров/охват")
    likes: int = Field(default=0, ge=0, description="Позитивные реакции / лайки")
    dislikes: int = Field(default=0, ge=0, description="Негативные реакции / дизлайки")
    comments_count: int = Field(default=0, ge=0, description="Количество комментариев")
    reposts: int = Field(default=0, ge=0, description="Пересылки / репосты (высокий вес)")
    bookmarks: int = Field(default=0, ge=0, description="Сохранения / закладки (высокий вес)")
    unsubscribes: int = Field(default=0, ge=0, description="Отписки после публикации")
    reactions_breakdown: Dict[str, int] = Field(default_factory=dict, description="Раскладка эмодзи: {'🔥': 40, '👍': 12}")
    raw_comments: List[str] = Field(default_factory=list, description="Тексты комментариев для семантического анализа")


class GenerationMetadataLink(BaseModel):
    """
    Жесткая связка метрик с контекстом исходной генерации в PipelineState.
    Гарантирует прямую атрибуцию результатов к использованным промптам и фреймворкам.
    """
    session_id: str = Field(default="", description="ID оригинальной сессии генерации PipelineState")
    post_id: str = Field(default="", description="Уникальный идентификатор публикации в соцсети")
    tenant_id: str = Field(default="default_tenant", description="Идентификатор изолированного тенанта")
    channel: str = Field(default="@UcustAi", description="Целевой канал/сообщество")
    platform: str = Field(default="telegram", description="telegram | vk")
    target_format: str = Field(default="post", description="Формат: post | storytelling | carousel | poll | quiz")
    munger_triggers: List[str] = Field(default_factory=list, description="Использованные триггеры Мангера")
    hunt_stage: Optional[str] = Field(None, description="Ступень лестницы Ханта")
    prompt_topic: str = Field(default="", description="Тема/инфоповод генерации")
    draft_snippet: str = Field(default="", description="Сниппет лид-абзаца (hook) сгенерированного поста")
    critic_score: float = Field(default=1.0, description="Оценка качества критика при генерации")


class PostTelemetryEvent(BaseModel):
    """
    Сырой контракт события телеметрии (Ingestion Layer).
    Поддерживает динамический сбор по временным окнам (1h, 24h, 7d).
    """
    event_id: str = Field(default_factory=lambda: f"telem_{int(time.time())}_{os.urandom(3).hex()}")
    post_id: str = Field(..., description="Идентификатор публикации в платформе")
    session_id: str = Field(..., description="ID связанной сессии генерации")
    tenant_id: str = Field(default="default_tenant")
    channel: str = Field(default="@UcustAi")
    platform: str = Field(default="telegram", description="telegram | vk")
    snapshot_window: str = Field(default="24h", description="Временной срез: 1h | 24h | 7d | final")
    metrics: TelemetryMetrics = Field(default_factory=TelemetryMetrics)
    generation_context: Optional[GenerationMetadataLink] = Field(None, description="Контекст генерации (если известен)")
    collected_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    @model_validator(mode="before")
    @classmethod
    def populate_context_ids(cls, data: Any) -> Any:
        if isinstance(data, dict):
            p_id = data.get("post_id", "")
            s_id = data.get("session_id", "")
            ctx = data.get("generation_context")
            if isinstance(ctx, dict):
                if not ctx.get("post_id"):
                    ctx["post_id"] = p_id
                if not ctx.get("session_id"):
                    ctx["session_id"] = s_id
                if not ctx.get("tenant_id") and data.get("tenant_id"):
                    ctx["tenant_id"] = data.get("tenant_id")
                if not ctx.get("channel") and data.get("channel"):
                    ctx["channel"] = data.get("channel")
                if not ctx.get("platform") and data.get("platform"):
                    ctx["platform"] = data.get("platform")
        return data

    @property
    def deduplication_key(self) -> str:
        """Ключ для O(1) upsert в БД/Redis (один пост + одно окно замера = одна запись)."""
        return f"{self.tenant_id}:{self.platform}:{self.post_id}:{self.snapshot_window}"


class EngagementScore(BaseModel):
    """
    Нормализованный скор вовлеченности:
    Рассчитывается относительно статистической базовой линии тенанта, а не абсолютных цифр.
    """
    raw_er: float = Field(..., description="Сырой взвешенный ER (%)")
    baseline_er: float = Field(..., description="Текущая базовая линия ER (%) тенанта/канала")
    z_score: float = Field(..., description="Z-Score отклонения от среднего значения базовой линии")
    normalized_score: float = Field(..., ge=0.0, le=1.0, description="Нормализованный балл 0.0 - 1.0 (Sigmoid)")
    tier: PerformanceTierEnum = Field(..., description="Грейд успешности: stellar | above_average | average | underperforming | critical_fail")
    positive_approval_index: float = Field(default=1.0, ge=0.0, le=1.0, description="NAI: Индекс чистого одобрения L / (L + D + 1)")
    is_statistically_significant: bool = Field(default=True, description="Флаг достоверности (просмотры >= 30)")
    calculated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


class TenantBaseline(BaseModel):
    """
    Статистическая базовая линия конкретного тенанта/канала.
    Исключает Self-Review Illusion и учитывает масштаб аудитории тенанта.
    """
    tenant_id: str = Field(...)
    channel: str = Field(...)
    platform: str = Field(default="telegram")
    sample_size: int = Field(default=0, ge=0, description="Количество проанализированных постов в выборке")
    mean_er: float = Field(default=2.5, description="Средний ER (%)")
    median_er: float = Field(default=2.5, description="Медианный ER (%)")
    std_dev_er: float = Field(default=1.0, description="Стандартное отклонение ER")
    risky_formats: List[str] = Field(default_factory=list, description="Форматы со стабильно низким ER (>= 60% провалов)")
    format_stats: Dict[str, Dict[str, float]] = Field(default_factory=dict, description="Статистика ER в разрезе форматов")
    last_calculated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


class FeedbackKnowledgeRefinement(BaseModel):
    """
    Контракт Append-Only обогащения базы знаний Clean RAG.
    Не изменяет исходный Brand DNA, а добавляет точечные контекстные ограничения и проверенные зацепы.
    """
    tenant_id: str = Field(...)
    session_id: str = Field(...)
    post_id: str = Field(...)
    proven_hooks: List[Dict[str, Any]] = Field(default_factory=list, description="Паттерны с высоким ER (type='proven_hook')")
    negative_constraints: List[Dict[str, Any]] = Field(default_factory=list, description="Антипаттерны с низким ER (type='negative_constraint')")
    recommendations: List[str] = Field(default_factory=list, description="Стратегические рекомендации для планирования")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


__all__ = [
    "PerformanceTierEnum",
    "TelemetryMetrics",
    "GenerationMetadataLink",
    "PostTelemetryEvent",
    "EngagementScore",
    "TenantBaseline",
    "FeedbackKnowledgeRefinement",
]

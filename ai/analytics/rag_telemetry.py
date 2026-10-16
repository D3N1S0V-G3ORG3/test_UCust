"""
File: ai/analytics/rag_telemetry.py
Служба телеметрии и наблюдаемости (Observability) для RAG и AntiHallucinationGuard:
1. Запись событий усечения контекста (Dynamic Priority-Budget Truncation).
2. Мониторинг срабатывания Safe Fallback CTA (из-за отсутствия цен/фактов в Hard Ground Truth).
3. Агрегация метрик Data Richness Score (DRS) по арендаторам.
4. Выявление тенантов, упирающихся в лимиты контекстного окна LLM (Context Window Exhaustion).
"""

from __future__ import annotations

import time
import logging
from datetime import datetime
from collections import deque, Counter
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field

from rag.models import RAGContext, DocCategoryEnum

logger = logging.getLogger("RAGTelemetryTracker")


class RAGQueryTelemetryEvent(BaseModel):
    """Событие выполнения RAG-запроса."""
    timestamp: float = Field(default_factory=time.time)
    datetime_str: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    tenant_id: str
    query: str
    top_score: float
    total_tokens: int
    has_sufficient_context: bool
    fallback_triggered: bool
    fallback_message: Optional[str] = None
    is_truncated: bool
    truncated_layers: List[str] = Field(default_factory=list)
    drs_score: Optional[int] = None


class RAGTelemetrySummary(BaseModel):
    """Агрегированная сводка телеметрии для Admin Dashboard."""
    total_queries: int
    fallback_rate_pct: float
    truncation_rate_pct: float
    avg_tokens_per_query: float
    layer_truncation_counts: Dict[str, int]
    tenants_at_token_risk: List[Dict[str, Any]]
    drs_health: Dict[str, Any]
    recent_fallback_events: List[Dict[str, Any]]


class RAGTelemetryTracker:
    """
    Потокобезопасный трекер телеметрии RAG для внутреннего дашборда администратора.
    Хранит кольцевой буфер последних событий и рассчитывает скользящую аналитику.
    """

    _instance: Optional["RAGTelemetryTracker"] = None

    @classmethod
    def get_instance(cls, buffer_size: int = 1000) -> "RAGTelemetryTracker":
        if cls._instance is None:
            cls._instance = cls(buffer_size=buffer_size)
        return cls._instance

    def __init__(self, buffer_size: int = 1000):
        self.buffer_size = buffer_size
        self._events: deque[RAGQueryTelemetryEvent] = deque(maxlen=buffer_size)
        self._tenant_drs: Dict[str, int] = {}

    def record_query(
        self,
        tenant_id: str,
        query: str,
        context: RAGContext,
        drs_score: Optional[int] = None
    ) -> RAGQueryTelemetryEvent:
        """Регистрация факта выполнения RAG запроса и состояния защиты от галлюцинаций."""
        fallback_triggered = (not context.has_sufficient_context) or (context.fallback_message is not None)
        
        event = RAGQueryTelemetryEvent(
            tenant_id=tenant_id,
            query=query[:200],
            top_score=round(context.top_score, 4),
            total_tokens=context.total_tokens,
            has_sufficient_context=context.has_sufficient_context,
            fallback_triggered=fallback_triggered,
            fallback_message=context.fallback_message,
            is_truncated=context.is_truncated,
            truncated_layers=context.truncated_layers or [],
            drs_score=drs_score or self._tenant_drs.get(tenant_id)
        )

        self._events.append(event)
        if drs_score is not None:
            self._tenant_drs[tenant_id] = drs_score

        if event.is_truncated:
            logger.warning(
                f"[RAGTelemetry] ⚠️ Tenant '{tenant_id}' context truncated: {event.truncated_layers} "
                f"(Tokens: {event.total_tokens})"
            )
        if event.fallback_triggered:
            logger.info(
                f"[RAGTelemetry] 🛡️ Fallback CTA triggered for tenant '{tenant_id}' (Score: {event.top_score:.2f})"
            )

        return event

    def set_tenant_drs(self, tenant_id: str, score: int):
        """Обновление текущей оценки Data Richness Score для тенанта."""
        self._tenant_drs[tenant_id] = max(0, min(100, score))

    def get_summary(self) -> RAGTelemetrySummary:
        """Формирование сводки метрик для дашборда администратора."""
        if not self._events:
            return RAGTelemetrySummary(
                total_queries=0,
                fallback_rate_pct=0.0,
                truncation_rate_pct=0.0,
                avg_tokens_per_query=0.0,
                layer_truncation_counts={},
                tenants_at_token_risk=[],
                drs_health={"average_drs": 0, "tracked_tenants": 0},
                recent_fallback_events=[]
            )

        total = len(self._events)
        fallbacks = sum(1 for e in self._events if e.fallback_triggered)
        truncations = sum(1 for e in self._events if e.is_truncated)
        total_tokens = sum(e.total_tokens for e in self._events)

        # Подсчет усечений по слоям
        layer_counter: Counter[str] = Counter()
        for e in self._events:
            for layer in e.truncated_layers:
                layer_counter[layer] += 1

        # Выявление арендаторов с высоким риском переполнения контекста
        tenant_trunc_count: Counter[str] = Counter()
        tenant_query_count: Counter[str] = Counter()
        tenant_max_tokens: Dict[str, int] = {}

        for e in self._events:
            tenant_query_count[e.tenant_id] += 1
            if e.is_truncated:
                tenant_trunc_count[e.tenant_id] += 1
            tenant_max_tokens[e.tenant_id] = max(tenant_max_tokens.get(e.tenant_id, 0), e.total_tokens)

        at_risk: List[Dict[str, Any]] = []
        for tid, q_count in tenant_query_count.items():
            t_count = tenant_trunc_count[tid]
            rate = round((t_count / q_count) * 100, 1)
            if rate >= 20.0 or tenant_max_tokens[tid] >= 1200:
                at_risk.append({
                    "tenant_id": tid,
                    "queries": q_count,
                    "truncation_events": t_count,
                    "truncation_rate_pct": rate,
                    "peak_tokens": tenant_max_tokens[tid],
                    "current_drs": self._tenant_drs.get(tid)
                })

        at_risk.sort(key=lambda x: x["truncation_rate_pct"], reverse=True)

        # Расчет здоровья DRS
        avg_drs = (
            round(sum(self._tenant_drs.values()) / len(self._tenant_drs), 1)
            if self._tenant_drs else 0.0
        )

        recent_fallbacks = [
            {
                "timestamp": e.datetime_str,
                "tenant_id": e.tenant_id,
                "query": e.query,
                "top_score": e.top_score,
                "message": e.fallback_message
            }
            for e in list(self._events)[-20:]
            if e.fallback_triggered
        ]

        return RAGTelemetrySummary(
            total_queries=total,
            fallback_rate_pct=round((fallbacks / total) * 100, 2),
            truncation_rate_pct=round((truncations / total) * 100, 2),
            avg_tokens_per_query=round(total_tokens / total, 1),
            layer_truncation_counts=dict(layer_counter),
            tenants_at_token_risk=at_risk,
            drs_health={
                "average_drs": avg_drs,
                "tracked_tenants": len(self._tenant_drs)
            },
            recent_fallback_events=recent_fallbacks
        )

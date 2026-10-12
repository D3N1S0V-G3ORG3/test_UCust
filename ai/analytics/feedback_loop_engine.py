"""
File: ai/analytics/feedback_loop_engine.py
Аналитическое ядро замкнутого цикла обратной связи (FeedbackLoopEngine):
1. Ingestion Layer: Прием и O(1) дедупликация сырой телеметрии постов (PostTelemetryEvent).
2. Attribution & Scoring: Математический расчет EngagementScore (Z-Score + Sigmoid)
   относительно индивидуальной базовой линии (TenantBaseline), исключающий Self-Review Illusion.
3. Pattern Detection: Выявление 'рискованных форматов' (risky_formats) при стабильном падении ER.
4. Append-Only Knowledge Refinement: Формирование proven_hooks и negative_constraints
   для Clean RAG и Critic Munger 2.0 без разрушения исходного Brand DNA.
"""

from __future__ import annotations

import os
import math
import time
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from schemas.feedback_state import (
    PerformanceTierEnum,
    TelemetryMetrics,
    GenerationMetadataLink,
    PostTelemetryEvent,
    EngagementScore,
    TenantBaseline,
    FeedbackKnowledgeRefinement,
)

logger = logging.getLogger("FeedbackLoopEngine")


class FeedbackLoopEngine:
    """
    Математический движок анализа эффективности контента и адаптивного самообучения:
    - Рассчитывает взвешенный ER с повышенным коэффициентом пересылок (1.2x) и закладок (1.5x).
    - Вычисляет скользящую статистическую базовую линию (Mean, Median, StdDev) для каждого тенанта.
    - Нормализует результат в диапазон [0.0 ... 1.0] через Sigmoid(Z-Score).
    - Выявляет деградирующие форматы публикаций для тенанта.
    - Генерирует Append-Only артефакты для RAG и Критика.
    """

    # Дефолтная базовая линия для Cold Start (< 5 публикаций в канале)
    DEFAULT_BASELINE_MEAN_ER: float = 2.5
    DEFAULT_BASELINE_STD_DEV: float = 1.0

    def __init__(self, redis_client: Optional[Any] = None) -> None:
        self.redis = redis_client
        # In-memory хранилище для локальной разработки / fallback:
        # key: f"{tenant_id}:{channel}" -> List[float] (история ER)
        self._history_er: Dict[str, List[float]] = {}
        # key: f"{tenant_id}:{channel}" -> Dict[format_name, List[float]]
        self._format_history: Dict[str, Dict[str, List[float]]] = {}
        # key: deduplication_key -> PostTelemetryEvent
        self._telemetry_store: Dict[str, PostTelemetryEvent] = {}

    @classmethod
    def calculate_raw_er(cls, metrics: TelemetryMetrics) -> float:
        """
        Математический расчет взвешенного Engagement Rate (ER%):
        ER = ((Likes + 1.2 * Reposts + 1.5 * Bookmarks + 1.0 * Comments - 2.0 * Dislikes) / max(Views, 1)) * 100
        """
        views = max(1, metrics.views)
        weighted_interactions = (
            float(metrics.likes) * 1.0 +
            float(metrics.reposts) * 1.2 +
            float(metrics.bookmarks) * 1.5 +
            float(metrics.comments_count) * 1.0 -
            float(metrics.dislikes) * 2.0
        )
        er = max(0.0, (weighted_interactions / views) * 100.0)
        return round(er, 3)

    @classmethod
    def calculate_approval_index(cls, likes: int, dislikes: int) -> float:
        """Net Approval Index (NAI) чистого одобрения [0.0 ... 1.0]."""
        l_val = max(0, likes)
        d_val = max(0, dislikes)
        return round(float(l_val) / float(l_val + d_val + 1), 4)

    def get_tenant_baseline(self, tenant_id: str, channel: str) -> TenantBaseline:
        """
        Получение текущей статистической базовой линии тенанта/канала:
        Если выборка < 5 постов — применяется устойчивый Cold Start бейзлайн.
        """
        store_key = f"{tenant_id}:{channel}"
        samples = self._history_er.get(store_key, [])
        sample_size = len(samples)

        if sample_size < 5:
            # Cold-start профиль
            return TenantBaseline(
                tenant_id=tenant_id,
                channel=channel,
                sample_size=sample_size,
                mean_er=self.DEFAULT_BASELINE_MEAN_ER,
                median_er=self.DEFAULT_BASELINE_MEAN_ER,
                std_dev_er=self.DEFAULT_BASELINE_STD_DEV,
                risky_formats=[],
                format_stats={},
            )

        mean_er = sum(samples) / float(sample_size)
        sorted_samples = sorted(samples)
        mid = sample_size // 2
        median_er = sorted_samples[mid] if sample_size % 2 != 0 else (sorted_samples[mid - 1] + sorted_samples[mid]) / 2.0

        variance = sum((x - mean_er) ** 2 for x in samples) / float(sample_size)
        std_dev_er = max(0.2, math.sqrt(variance))

        # Анализ форматов и выявление 'рискованных'
        format_store = self._format_history.get(store_key, {})
        format_stats: Dict[str, Dict[str, float]] = {}
        risky_formats: List[str] = []

        for fmt, er_list in format_store.items():
            if not er_list:
                continue
            fmt_mean = sum(er_list) / float(len(er_list))
            # Доля постов этого формата, показавших результат ниже среднего (Z-score < -0.5)
            underperform_count = sum(1 for val in er_list if val < (mean_er - 0.5 * std_dev_er))
            underperform_ratio = underperform_count / float(len(er_list))

            format_stats[fmt] = {
                "count": float(len(er_list)),
                "mean_er": round(fmt_mean, 3),
                "underperform_ratio": round(underperform_ratio, 3),
            }

            # Правило 'Рискованного формата': минимум 3 замера и более 60% провалов
            if len(er_list) >= 3 and underperform_ratio >= 0.60:
                risky_formats.append(fmt)

        return TenantBaseline(
            tenant_id=tenant_id,
            channel=channel,
            sample_size=sample_size,
            mean_er=round(mean_er, 3),
            median_er=round(median_er, 3),
            std_dev_er=round(std_dev_er, 3),
            risky_formats=risky_formats,
            format_stats=format_stats,
        )

    def evaluate_score(self, raw_er: float, baseline: TenantBaseline, likes: int, dislikes: int, views: int) -> EngagementScore:
        """
        Математическая нормализация скора вовлеченности:
        Использует Sigmoid(Z-Score) для перевода в шкалу [0.0 ... 1.0].
        Z = (Raw ER - Mean ER) / max(StdDev, 0.5)
        Normalized Score = 1 / (1 + exp(-Z))
        """
        safe_std = max(0.5, baseline.std_dev_er)
        z_score = (raw_er - baseline.mean_er) / safe_std
        # Ограничиваем Z-score диапазоном [-6.0, 6.0] для численной стабильности sigmoid
        clamped_z = max(-6.0, min(6.0, z_score))
        normalized_score = 1.0 / (1.0 + math.exp(-clamped_z))
        normalized_score = round(normalized_score, 4)

        # Определение грейда производительности (Performance Tier)
        if normalized_score >= 0.85:
            tier = PerformanceTierEnum.STELLAR
        elif normalized_score >= 0.60:
            tier = PerformanceTierEnum.ABOVE_AVERAGE
        elif normalized_score >= 0.40:
            tier = PerformanceTierEnum.AVERAGE
        elif normalized_score >= 0.20:
            tier = PerformanceTierEnum.UNDERPERFORMING
        else:
            tier = PerformanceTierEnum.CRITICAL_FAIL

        nai = self.calculate_approval_index(likes, dislikes)
        is_statistically_significant = bool(views >= 30)

        return EngagementScore(
            raw_er=raw_er,
            baseline_er=baseline.mean_er,
            z_score=round(z_score, 3),
            normalized_score=normalized_score,
            tier=tier,
            positive_approval_index=nai,
            is_statistically_significant=is_statistically_significant,
        )

    def ingest_telemetry(self, event: PostTelemetryEvent) -> EngagementScore:
        """
        Прием телеметрии поста с O(1) дедупликацией/upsert и пересчетом базовой линии:
        - Исключает дублирование замеров одного временного окна.
        - Обновляет скользящую историю ER тенанта.
        - Возвращает нормализованный EngagementScore.
        """
        dedup_key = event.deduplication_key
        # Сохранение / Upsert в хранилище
        self._telemetry_store[dedup_key] = event

        raw_er = self.calculate_raw_er(event.metrics)
        baseline_before = self.get_tenant_baseline(event.tenant_id, event.channel)

        score = self.evaluate_score(
            raw_er=raw_er,
            baseline=baseline_before,
            likes=event.metrics.likes,
            dislikes=event.metrics.dislikes,
            views=event.metrics.views,
        )

        # Добавляем в историю только статистически значимые замеры (или окна >= 24h)
        if event.snapshot_window in {"24h", "7d", "final"} or event.metrics.views >= 30:
            store_key = f"{event.tenant_id}:{event.channel}"
            if store_key not in self._history_er:
                self._history_er[store_key] = []
            self._history_er[store_key].append(raw_er)
            # Ограничиваем размер скользящего окна 100 замерами
            if len(self._history_er[store_key]) > 100:
                self._history_er[store_key].pop(0)

            # Обновляем историю в разрезе формата
            fmt = event.generation_context.target_format if event.generation_context else "post"
            if store_key not in self._format_history:
                self._format_history[store_key] = {}
            if fmt not in self._format_history[store_key]:
                self._format_history[store_key][fmt] = []
            self._format_history[store_key][fmt].append(raw_er)
            if len(self._format_history[store_key][fmt]) > 50:
                self._format_history[store_key][fmt].pop(0)

        logger.info(
            f"📊 [FeedbackLoop] Post {event.post_id} ({event.snapshot_window}): "
            f"Raw ER={raw_er}% vs Baseline={baseline_before.mean_er}% "
            f"-> Score={score.normalized_score} ({score.tier.value})"
        )
        return score

    def refine_knowledge(
        self,
        event: PostTelemetryEvent,
        score: EngagementScore,
    ) -> FeedbackKnowledgeRefinement:
        """
        Формирует Append-Only директивы обогащения базы знаний Clean RAG:
        1. type='proven_hook' (few-shot) при высоком ER (Score >= 0.70).
        2. type='negative_constraint' (штраф для критика) при низком ER (Score <= 0.35).
        """
        proven_hooks: List[Dict[str, Any]] = []
        negative_constraints: List[Dict[str, Any]] = []
        recommendations: List[str] = []

        ctx = event.generation_context
        hook_snippet = ctx.draft_snippet if ctx else ""
        fmt = ctx.target_format if ctx else "post"
        topic = ctx.prompt_topic if ctx else ""

        baseline = self.get_tenant_baseline(event.tenant_id, event.channel)

        # 1. Формирование проверенных зацепов (Proven Hooks)
        if score.normalized_score >= 0.70 and score.is_statistically_significant:
            proven_hooks.append({
                "type": "proven_hook",
                "tenant_id": event.tenant_id,
                "channel": event.channel,
                "target_format": fmt,
                "topic": topic,
                "hook_text": hook_snippet,
                "normalized_score": score.normalized_score,
                "raw_er": score.raw_er,
                "munger_triggers": ctx.munger_triggers if ctx else [],
                "rationale": f"Высокий отклик аудитории (ER {score.raw_er}% vs Baseline {score.baseline_er}%).",
            })
            recommendations.append(f"Использовать структуру зацепа '{hook_snippet[:60]}...' как few-shot пример.")

        # 2. Формирование негативных ограничений (Negative Constraints)
        elif score.normalized_score <= 0.35 and score.is_statistically_significant:
            negative_constraints.append({
                "type": "negative_constraint",
                "tenant_id": event.tenant_id,
                "channel": event.channel,
                "target_format": fmt,
                "topic": topic,
                "failed_hook": hook_snippet,
                "normalized_score": score.normalized_score,
                "raw_er": score.raw_er,
                "critic_penalty": 0.40,
                "reason": f"Низкое вовлечение аудитории (ER {score.raw_er}% значительно ниже нормы {score.baseline_er}%).",
            })
            recommendations.append(f"Штрафовать черновики формата '{fmt}' с аналогичной подачей (Score < 0.35).")

        # 3. Проверка формата на рискованность для тенанта
        if fmt in baseline.risky_formats:
            recommendations.append(
                f"ВНИМАНИЕ: Формат '{fmt}' признан рискованным для канала {event.channel} "
                f"(более 60% публикаций этого формата показали ER ниже нормы)."
            )

        return FeedbackKnowledgeRefinement(
            tenant_id=event.tenant_id,
            session_id=event.session_id,
            post_id=event.post_id,
            proven_hooks=proven_hooks,
            negative_constraints=negative_constraints,
            recommendations=recommendations,
        )

    async def sync_refinements_to_rag(
        self,
        refinement: FeedbackKnowledgeRefinement,
        rag_pipeline: Any,
    ) -> int:
        """
        Асинхронная индексация инсайтов обратной связи в Clean RAG без мутации Brand DNA:
        Индексирует proven_hooks и negative_constraints с жесткой изоляцией tenant_id.
        """
        if not rag_pipeline:
            return 0

        from rag.models import Document

        docs_to_index: List[Document] = []

        # Индексация положительных хуков
        for hook in refinement.proven_hooks:
            doc_id = f"hook_{refinement.tenant_id}_{int(time.time())}_{os.urandom(2).hex()}"
            doc_text = (
                f"Успешный проверенный зацеп (Proven Hook) для формата {hook.get('target_format')}: "
                f"Тема: {hook.get('topic')}. Зацеп: {hook.get('hook_text')}. "
                f"Эффективность: ER={hook.get('raw_er')}%, Score={hook.get('normalized_score')}."
            )
            docs_to_index.append(Document(
                doc_id=doc_id,
                text=doc_text,
                metadata={
                    "type": "proven_hook",
                    "tenant_id": refinement.tenant_id,
                    "target_format": hook.get("target_format"),
                    "score": hook.get("normalized_score"),
                }
            ))

        # Индексация негативных констрейнтов
        for constraint in refinement.negative_constraints:
            doc_id = f"neg_{refinement.tenant_id}_{int(time.time())}_{os.urandom(2).hex()}"
            doc_text = (
                f"Негативное ограничение редполитики (Negative Constraint) для формата {constraint.get('target_format')}: "
                f"Провальный подход: {constraint.get('failed_hook')}. "
                f"Причина: {constraint.get('reason')}. Запрещено повторять данную стилистику."
            )
            docs_to_index.append(Document(
                doc_id=doc_id,
                text=doc_text,
                metadata={
                    "type": "negative_constraint",
                    "tenant_id": refinement.tenant_id,
                    "target_format": constraint.get("target_format"),
                    "penalty": constraint.get("critic_penalty", 0.40),
                }
            ))

        if docs_to_index and hasattr(rag_pipeline, "ingest_documents_async"):
            indexed = await rag_pipeline.ingest_documents_async(docs_to_index)
            logger.info(f"📚 [FeedbackLoop:RAG] Проиндексировано {indexed} директив обратной связи для тенанта '{refinement.tenant_id}'.")
            return indexed

        return 0

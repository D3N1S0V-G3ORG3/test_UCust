"""
File: ai/services/trend_service.py
Семантический слой Trend Engine (Semantic Agent Layer).
Отвечает за:
1. Обогащение математических кластеров (TrendCluster) семантикой через Saiga LLM.
2. Принудительную валидацию JSON-структуры под строгий контракт TrendState.
3. Щадящий последовательный батчинг с очисткой VRAM (torch.cuda.empty_cache()) для Zephyrus S17.
4. RAG-индексацию с мета-тегами (type="trend_agenda") и механизмом TTL-эвикции.
"""

from __future__ import annotations

import os
import re
import json
import uuid
import time
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from schemas.trend_state import (
    RawTrendEvent,
    TrendCluster,
    TrendState,
    TrendLifecycleEnum,
    TrendSentimentEnum,
)
from analytics.trend_clusterer import TrendClusterer
from rag.models import Document

logger = logging.getLogger("TrendService")


class TrendService:
    """
    Доменный сервис семантического анализа трендов:
    - Оркестрирует сбор, дедупликацию и кластеризацию.
    - Выполняет локальный LLM-инференс без галлюцинаций (Zero Hallucination Guard).
    - Индексирует тренды в Clean RAG Pipeline с метаданными времени жизни (TTL).
    """

    def __init__(
        self,
        clusterer: Optional[TrendClusterer] = None,
        rag_pipeline: Optional[Any] = None,
        redis_cache: Optional[Any] = None,
    ):
        self.clusterer = clusterer or TrendClusterer()
        self.rag = rag_pipeline
        self.redis_cache = redis_cache
        self._llm_skill = None
        self._init_llm()

    def _init_llm(self):
        try:
            from skills.saiga_llm import SaigaLLMSkill
            self._llm_skill = SaigaLLMSkill()
        except Exception as e:
            logger.warning(f"[TrendService] SaigaLLMSkill недоступен: {e}. Будет использован Rule-Based fallback.")
            self._llm_skill = None

    def _clean_vram(self):
        """Очистка видеопамяти после каждого батча для предотвращения OOM (Zephyrus S17)."""
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def _extract_json_from_response(self, raw_text: str) -> Optional[dict]:
        """Извлекает и валидирует чистый JSON объект из текстового ответа LLM."""
        if not raw_text:
            return None
        # Поиск блока ```json ... ```
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
        candidate = match.group(1) if match else raw_text

        # Поиск первого сбалансированного {...}
        brace_match = re.search(r"(\{.*\})", candidate, re.DOTALL)
        if brace_match:
            candidate = brace_match.group(1)

        try:
            return json.loads(candidate)
        except Exception:
            # Попытка подчистить висячие запятые
            clean_sub = re.sub(r",\s*([\}\]])", r"\1", candidate)
            try:
                return json.loads(clean_sub)
            except Exception:
                return None

    def _heuristic_semantic_analysis(self, cluster: TrendCluster) -> Dict[str, Any]:
        """
        Высокоскоростной детерминированный fallback, если локальная LLM не загружена в VRAM.
        Извлекает ключевые сущности, формирует headline и оценивает тональность.
        """
        texts = cluster.centroid_representative_texts
        first_text = texts[0] if texts else "Актуальное событие в индустрии"
        # Первое предложение или до 120 символов
        first_sentence = first_text.split(".")[0].strip()
        if len(first_sentence) > 140:
            first_sentence = first_sentence[:137].rsplit(" ", 1)[0] + "..."

        headline = f"Всплеск обсуждений: {first_sentence}"

        # Извлечение сущностей (слова с заглавной буквы / аббревиатуры)
        entities = set()
        for t in texts:
            words = re.findall(r"\b[A-ZА-ЯЁ][a-zа-яёA-ZА-ЯЁ0-9_-]+\b", t)
            for w in words:
                if len(w) > 3 and w.lower() not in {"новый", "новые", "сегодня", "срочно", "очень", "также"}:
                    entities.add(w)

        sentiment = TrendSentimentEnum.NEUTRAL
        all_text_lower = " ".join(texts).lower()
        if any(w in all_text_lower for w in ["рекорд", "успех", "прорыв", "лучший", "рост", "победа", "инновац"]):
            sentiment = TrendSentimentEnum.POSITIVE
        elif any(w in all_text_lower for w in ["сбой", "падение", "убыток", "кризис", "ошибка", "запрет", "скандал"]):
            sentiment = TrendSentimentEnum.NEGATIVE

        lifecycle = TrendLifecycleEnum.MICRO_HYPE if cluster.density_spike > 2.0 else TrendLifecycleEnum.MACRO_TREND

        summary = f"Кластер из {cluster.total_samples} сообщений со скоростью {cluster.velocity_score} сообщ/час. Основные аспекты: " + "; ".join(texts[:3])

        return {
            "topic_headline": headline,
            "summary": summary,
            "niche_categories": ["Общее", "Инновации"],
            "trend_lifecycle": lifecycle.value,
            "sentiment": sentiment.value,
            "key_entities": list(entities)[:6],
            "relevance_score": min(0.95, round(0.5 + (cluster.density_spike * 0.1), 2)),
        }

    async def analyze_cluster_to_trend(self, cluster: TrendCluster) -> TrendState:
        """
        Семантический анализ отдельного кластера через Saiga LLM с валидацией Pydantic схемы.
        """
        start_time = time.time()
        rep_texts = "\n---\n".join([f"[{i+1}] {t}" for i, t in enumerate(cluster.centroid_representative_texts)])

        prompt = (
            "Ты — строгий аналитик данных и инфоповодов. Проанализируй кластер текстов из социальных сетей:\n\n"
            f"{rep_texts}\n\n"
            "Сформулируй аналитический отчет ТОЛЬКО в формате JSON со следующими полями:\n"
            "{\n"
            '  "topic_headline": "Краткая суть инфоповода ровно в одном предложении (до 15 слов)",\n'
            '  "summary": "Развернутое резюме инфоповода (2-3 предложения) строго по фактам из текстов",\n'
            '  "niche_categories": ["Категория 1", "Категория 2"],\n'
            '  "trend_lifecycle": "micro_hype" или "macro_trend",\n'
            '  "sentiment": "positive", "neutral" или "negative",\n'
            '  "key_entities": ["Сущность 1", "Сущность 2"],\n'
            '  "relevance_score": число от 0.1 до 1.0 (коммерческая применимость для рекламы)\n'
            "}\n"
            "Запрещено выдумывать факты, которых нет в текстах. Отвечай ТОЛЬКО чистым валидным JSON."
        )

        semantic_data = None
        tokens_est = cluster.total_representative_tokens + 150

        if self._llm_skill is not None and getattr(self._llm_skill, "_is_loaded", False):
            try:
                raw_response = self._llm_skill._generate_raw(prompt)
                semantic_data = self._extract_json_from_response(raw_response)
            except Exception as e:
                logger.warning(f"[TrendService] Ошибка LLM инференса: {e}. Применен fallback.")

        if not semantic_data:
            semantic_data = self._heuristic_semantic_analysis(cluster)

        # Безопасный парсинг перечислений
        lifecycle = TrendLifecycleEnum.MICRO_HYPE
        if str(semantic_data.get("trend_lifecycle")).lower() == "macro_trend":
            lifecycle = TrendLifecycleEnum.MACRO_TREND

        sentiment = TrendSentimentEnum.NEUTRAL
        sent_str = str(semantic_data.get("sentiment")).lower()
        if "pos" in sent_str:
            sentiment = TrendSentimentEnum.POSITIVE
        elif "neg" in sent_str:
            sentiment = TrendSentimentEnum.NEGATIVE

        trend_id = f"tr_{cluster.cluster_id}"
        trend_state = TrendState(
            trend_id=trend_id,
            cluster_id=cluster.cluster_id,
            topic_headline=semantic_data.get("topic_headline", "Актуальный инфоповод"),
            summary=semantic_data.get("summary", ""),
            niche_categories=semantic_data.get("niche_categories", ["Бизнес"]),
            trend_lifecycle=lifecycle,
            sentiment=sentiment,
            key_entities=semantic_data.get("key_entities", []),
            relevance_score=float(semantic_data.get("relevance_score", 0.7)),
            source_references=cluster.media_samples,
            velocity_growth_rate=cluster.density_spike,
            tokens_consumed=tokens_est,
            analyzed_at=datetime.utcnow(),
            is_actionable=True,
        )

        self._clean_vram()
        logger.info(f"[TrendService] ✅ Кластер '{cluster.cluster_id}' успешно проанализирован: '{trend_state.topic_headline[:60]}...'")
        return trend_state

    async def process_clusters(self, clusters: List[TrendCluster]) -> List[TrendState]:
        """Последовательная щадящая обработка списка кластеров."""
        trends: List[TrendState] = []
        for cl in clusters:
            try:
                state = await self.analyze_cluster_to_trend(cl)
                trends.append(state)
            except Exception as e:
                logger.error(f"[TrendService] Ошибка обработки кластера {cl.cluster_id}: {e}")
        return trends

    # -------------------------------------------------------------------------
    # RAG Индексация с механизмом TTL и фильтрацией
    # -------------------------------------------------------------------------

    async def index_trends_to_rag(
        self,
        trends: List[TrendState],
        tenant_id: str = "default_tenant"
    ) -> int:
        """
        Индексирует верифицированные тренды в Clean RAG Pipeline
        с жестким тегом type="trend_agenda" и TTL-метаданными.
        """
        if not self.rag or not trends:
            return 0

        documents: List[Document] = []
        for tr in trends:
            ttl_h = 48.0 if tr.trend_lifecycle == TrendLifecycleEnum.MICRO_HYPE else 720.0
            doc_text = (
                f"Инфоповод: {tr.topic_headline}\n"
                f"Резюме: {tr.summary}\n"
                f"Тематики: {', '.join(tr.niche_categories)}\n"
                f"Ключевые сущности: {', '.join(tr.key_entities)}\n"
                f"Тональность: {tr.sentiment.value}\n"
                f"Скорость распространения: {tr.velocity_growth_rate}x"
            )
            meta = {
                "type": "trend_agenda",
                "trend_id": tr.trend_id,
                "cluster_id": tr.cluster_id,
                "sentiment": tr.sentiment.value,
                "lifecycle": tr.trend_lifecycle.value,
                "relevance_score": tr.relevance_score,
                "created_at": tr.analyzed_at.isoformat(),
                "ttl_hours": ttl_h,
                "tenant_id": tenant_id,
            }
            doc = Document(
                doc_id=f"doc_{tr.trend_id}",
                text=doc_text,
                metadata=meta
            )
            documents.append(doc)

        indexed_count = await self.rag.ingest_documents_async(documents)
        logger.info(f"[TrendService] 📥 Успешно проиндексировано {indexed_count} чанков инфоповодов в Clean RAG Pipeline.")
        return indexed_count

    @classmethod
    def filter_active_trend_documents(cls, candidate_chunks: List[Any], max_age_hours: float = 48.0) -> List[Any]:
        """
        Фильтр устаревших инфоповодов (TTL Eviction) на этапе извлечения из векторной базы.
        Исключает мемы и хайпы старше допустимого времени жизни (по умолчанию 48ч).
        """
        now = datetime.utcnow()
        active = []
        for ch in candidate_chunks:
            meta = getattr(ch, "metadata", None)
            if meta is None and hasattr(ch, "chunk"):
                meta = getattr(ch.chunk, "metadata", {}) or {}
            meta = meta or {}
            if meta.get("type") != "trend_agenda":
                active.append(ch)
                continue


            created_str = meta.get("created_at")
            ttl_h = float(meta.get("ttl_hours", max_age_hours))
            if created_str:
                try:
                    dt = datetime.fromisoformat(created_str)
                    age_h = (now - dt).total_seconds() / 3600.0
                    if age_h > ttl_h:
                        continue  # Исключаем протухший инфоповод
                except Exception:
                    pass
            active.append(ch)
        return active

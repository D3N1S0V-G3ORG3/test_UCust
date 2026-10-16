"""
4. Context Injection & Anti-Hallucination Guard
Форматирование найденных чанков с метаданными и пороговая фильтрация (score >= 0.55).
Защита генеративной модели от галлюцинаций с поддержкой 4-слойной стратификации знаний:
1. Hard Ground Truth (hard_fact) - Жесткие факты (цены, составы, сроки)
2. Brand DNA & Redpolicy (brand_dna) - ToV, эталоны, правила платформ
3. Audience Priors (audience_priors) - Боли, триггеры, FAQ
4. Episodic Memory (episodic_memory) - Свежие директивы владельца
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from typing import List, Dict, Optional, Any
from rag.models import RetrievalResult, RAGContext, Chunk, DocCategoryEnum, TrustTierEnum, PlatformTargetEnum


class AntiHallucinationGuard:
    """
    RAG-Guard & Stratified Context Injector:
    1. Проверяет релевантность найденных данных по порогу (score threshold).
    2. Стратифицирует найденные чанки по 4 фундаментальным слоям базы знаний.
    3. Упаковывает чанки с прозрачными метаданными (источник, дата, скор, доверие, платформа).
    4. Запрещает генеративной модели придумывать факты, если в Hard Ground Truth слое нет ответа.
    """

    LAYER_TITLES = {
        DocCategoryEnum.HARD_FACT.value: "=== СЛОЙ 1: HARD GROUND TRUTH (ЖЁСТКИЕ ФАКТЫ: Цены, Характеристики, Условия — Запрещено выдумывать) ===",
        DocCategoryEnum.BRAND_DNA.value: "=== СЛОЙ 2: BRAND DNA & REDPOLICY (Тон коммуникации, Редполитика, Примеры ❌ / ✅) ===",
        DocCategoryEnum.AUDIENCE_PRIORS.value: "=== СЛОЙ 3: AUDIENCE PRIORS (Боли, Триггеры, FAQ, Возражения ЦА) ===",
        DocCategoryEnum.EPISODIC_MEMORY.value: "=== СЛОЙ 4: EPISODIC MEMORY (Директивы, Правки, Стоп-слова — Наивысший приоритет) ===",
        "general": "=== МАТЕРИАЛЫ БАЗЫ ЗНАНИЙ ==="
    }

    LAYER_DIRECTIVES = (
        "### СТРАТИФИЦИРОВАННЫЙ КОНТЕКСТ БАЗЫ ЗНАНИЙ (4 СЛОЯ UCust RAG) ###\n"
        "[ПРАВИЛА И ПРИОРИТЕТЫ ИСПОЛЬЗОВАНИЯ:]\n"
        "1. HARD GROUND TRUTH: Строгое ядро фактов. Цены, скидки, составы и условия разрешено брать ТОЛЬКО отсюда. "
        "Если информации нет — додумывание строго запрещено (использовать безопасный CTA).\n"
        "2. BRAND DNA & REDPOLICY: Определяет тональность, стиль, структуру поста, стоп-слова и антипримеры.\n"
        "3. AUDIENCE PRIORS: Боли и потребности целевой аудитории. Используй для вовлекающих хуков, опросов и аргументации.\n"
        "4. EPISODIC MEMORY: Свежие директивы и корректировки владельца. Имеют НАИВЫСШИЙ приоритет и переопределяют общие шаблоны."
    )

    def __init__(self, min_confidence_threshold: float = 0.55):
        self.min_confidence_threshold = min_confidence_threshold

    @staticmethod
    def _normalize_category(chunk: Chunk) -> str:
        cat = (chunk.metadata.get("doc_category") or chunk.metadata.get("category") or "").strip().lower()
        if cat in {"hard_fact", "grounded_facts", "price", "specs", "hard_facts", "pricing"}:
            return DocCategoryEnum.HARD_FACT.value
        if cat in {"brand_dna", "redpolicy", "tone_of_voice", "tov", "brand_rules", "brand_fact"}:
            return DocCategoryEnum.BRAND_DNA.value
        if cat in {"audience_priors", "pains", "triggers", "faq", "niche_prior", "audience"}:
            return DocCategoryEnum.AUDIENCE_PRIORS.value
        if cat in {"episodic_memory", "directives", "feedback", "moderation_log", "directive", "memory"}:
            return DocCategoryEnum.EPISODIC_MEMORY.value
        return "general"

    def format_and_guard(self, query: str, results: List[RetrievalResult]) -> RAGContext:
        """
        Форматирует стратифицированный контекст и применяет Guardrail защиты от галлюцинаций.
        """
        if not results:
            return RAGContext(
                query=query,
                formatted_context="",
                chunks=[],
                top_score=0.0,
                has_sufficient_context=False,
                fallback_message="В проверенной базе знаний UCust нет подтвержденной информации по вашему запросу. Генерация фактов запрещена во избежание галлюцинаций.",
                stratified_layers={
                    DocCategoryEnum.HARD_FACT.value: [],
                    DocCategoryEnum.BRAND_DNA.value: [],
                    DocCategoryEnum.AUDIENCE_PRIORS.value: [],
                    DocCategoryEnum.EPISODIC_MEMORY.value: [],
                }
            )

        top_score = max((r.rerank_score for r in results), default=0.0)

        # Проверка порога уверенности RAG-Guard
        if top_score < self.min_confidence_threshold:
            return RAGContext(
                query=query,
                formatted_context="",
                chunks=[r.chunk for r in results],
                top_score=top_score,
                has_sufficient_context=False,
                fallback_message=(
                    f"Уровень релевантности найденных документов ({top_score:.2f}) ниже порога безопасности ({self.min_confidence_threshold:.2f}). "
                    "Недостаточно фактуры для гарантированно точного ответа. Додумывание цифр и фактов запрещено."
                ),
                stratified_layers={
                    DocCategoryEnum.HARD_FACT.value: [],
                    DocCategoryEnum.BRAND_DNA.value: [],
                    DocCategoryEnum.AUDIENCE_PRIORS.value: [],
                    DocCategoryEnum.EPISODIC_MEMORY.value: [],
                }
            )

        # 1. Группировка чанков по 4 слоям
        layer_groups: Dict[str, List[RetrievalResult]] = {
            DocCategoryEnum.HARD_FACT.value: [],
            DocCategoryEnum.BRAND_DNA.value: [],
            DocCategoryEnum.AUDIENCE_PRIORS.value: [],
            DocCategoryEnum.EPISODIC_MEMORY.value: [],
            "general": []
        }

        for res in results:
            cat = self._normalize_category(res.chunk)
            layer_groups[cat].append(res)

        # Сортируем эпизодическую память по дате (свежие директивы первыми)
        layer_groups[DocCategoryEnum.EPISODIC_MEMORY.value].sort(
            key=lambda r: r.chunk.created_at,
            reverse=True
        )

        # 2. Формирование структурированного текстового контекста
        has_any_stratified = any(
            len(layer_groups[k]) > 0 for k in [
                DocCategoryEnum.HARD_FACT.value,
                DocCategoryEnum.BRAND_DNA.value,
                DocCategoryEnum.AUDIENCE_PRIORS.value,
                DocCategoryEnum.EPISODIC_MEMORY.value,
            ]
        )

        context_sections = []
        if has_any_stratified:
            context_sections.append(self.LAYER_DIRECTIVES)

        ordered_layers = [
            DocCategoryEnum.HARD_FACT.value,
            DocCategoryEnum.BRAND_DNA.value,
            DocCategoryEnum.AUDIENCE_PRIORS.value,
            DocCategoryEnum.EPISODIC_MEMORY.value,
            "general"
        ]

        total_idx = 1
        for layer_key in ordered_layers:
            items = layer_groups[layer_key]
            if not items:
                continue

            section_header = self.LAYER_TITLES.get(layer_key, f"=== СЛОЙ: {layer_key.upper()} ===")
            chunk_blocks = []
            for res in items:
                chunk = res.chunk
                source = chunk.source or "unknown"
                date_str = chunk.created_at[:10] if chunk.created_at else "recent"
                trust = chunk.metadata.get("trust_tier") or "verified_automated"
                platform = chunk.metadata.get("platform_target") or "all"
                
                header = (
                    f"[ИСТОЧНИК #{total_idx}: {source} | Доверие: {trust} | "
                    f"Платформа: {platform} | Дата: {date_str} | ID: {chunk.chunk_id} | Score: {res.rerank_score:.2f}]"
                )
                chunk_blocks.append(f"{header}\n{chunk.text}")
                total_idx += 1

            context_sections.append(section_header + "\n" + "\n\n".join(chunk_blocks))

        formatted_context_str = "\n\n" + ("\n\n" + "-" * 40 + "\n\n").join(context_sections)

        stratified_dict = {
            DocCategoryEnum.HARD_FACT.value: [r.chunk for r in layer_groups[DocCategoryEnum.HARD_FACT.value]],
            DocCategoryEnum.BRAND_DNA.value: [r.chunk for r in layer_groups[DocCategoryEnum.BRAND_DNA.value]],
            DocCategoryEnum.AUDIENCE_PRIORS.value: [r.chunk for r in layer_groups[DocCategoryEnum.AUDIENCE_PRIORS.value]],
            DocCategoryEnum.EPISODIC_MEMORY.value: [r.chunk for r in layer_groups[DocCategoryEnum.EPISODIC_MEMORY.value]],
        }

        return RAGContext(
            query=query,
            formatted_context=formatted_context_str.strip(),
            chunks=[r.chunk for r in results],
            top_score=top_score,
            has_sufficient_context=True,
            fallback_message=None,
            stratified_layers=stratified_dict
        )

"""
4. Context Injection & Anti-Hallucination Guard
Форматирование найденных чанков с метаданными и пороговая фильтрация (score >= 0.55).
Защита генеративной модели от галлюцинаций с поддержкой 4-слойной стратификации знаний:
1. Hard Ground Truth (hard_fact) - Жесткие факты (цены, составы, сроки) [Tier 1: 100% квота, никогда не обрезается]
2. Episodic Memory (episodic_memory) - Свежие директивы владельца [Tier 2: Top-3 LIFO директивы]
3. Brand DNA & Redpolicy (brand_dna) - ToV, эталоны, правила платформ [Tier 3: Бюджетируемый слой]
4. Audience Priors (audience_priors) - Боли, триггеры, FAQ [Tier 4: Эластичный деградируемый слой]
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import logging
from typing import List, Dict, Optional, Any
from rag.models import RetrievalResult, RAGContext, Chunk, DocCategoryEnum, TrustTierEnum, PlatformTargetEnum

logger = logging.getLogger("AntiHallucinationGuard")


class AntiHallucinationGuard:
    """
    RAG-Guard & Stratified Context Injector:
    1. Проверяет релевантность найденных данных по порогу (score threshold).
    2. Стратифицирует найденные чанки по 4 фундаментальным слоям базы знаний.
    3. Упаковывает чанки с прозрачными метаданными (источник, дата, скор, доверие, платформа).
    4. Предотвращает Token Overflow через механизм умной деградации (Dynamic Priority-Budget Truncation).
    5. Запрещает генеративной модели придумывать факты, если в Hard Ground Truth слое нет ответа.
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

    def __init__(
        self,
        min_confidence_threshold: float = 0.55,
        max_context_tokens: int = 1500,
        max_episodic_directives: int = 3
    ):
        self.min_confidence_threshold = min_confidence_threshold
        self.max_context_tokens = max_context_tokens
        self.max_episodic_directives = max_episodic_directives

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Быстрая эвристика BPE токенов для русско-английских текстов (~1.3 токена на слово)."""
        if not text:
            return 0
        return max(1, int(len(text.split()) * 1.3))

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
        Форматирует стратифицированный контекст с применением Dynamic Priority-Budget Truncation.
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
                },
                total_tokens=0,
                is_truncated=False,
                truncated_layers=[]
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
                },
                total_tokens=0,
                is_truncated=False,
                truncated_layers=[]
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

        # 2. Темпоральная приоритизация Episodic Memory (LIFO)
        truncated_layers: List[str] = []
        episodic_items = layer_groups[DocCategoryEnum.EPISODIC_MEMORY.value]
        episodic_items.sort(key=lambda r: r.chunk.created_at, reverse=True)

        if len(episodic_items) > self.max_episodic_directives:
            truncated_layers.append(DocCategoryEnum.EPISODIC_MEMORY.value)
            layer_groups[DocCategoryEnum.EPISODIC_MEMORY.value] = episodic_items[:self.max_episodic_directives]

        # 3. Dynamic Priority-Budget Truncation (Умная деградация контекста)
        # Бюджет распределяется строго по иерархии:
        # Tier 1 (hard_fact): 100% неприкосновенная квота
        # Tier 2 (episodic_memory): Top-N директивы
        # Tier 3 (brand_dna): Редполитика укладывается в доступный остаток
        # Tier 4 (audience_priors): Эластичный слой, деградирует/обрезается первым при переполнении
        
        header_tokens = self._estimate_tokens(self.LAYER_DIRECTIVES)
        hard_items = layer_groups[DocCategoryEnum.HARD_FACT.value]
        hard_tokens = sum(self._estimate_tokens(r.chunk.text) for r in hard_items)
        episodic_tokens = sum(self._estimate_tokens(r.chunk.text) for r in layer_groups[DocCategoryEnum.EPISODIC_MEMORY.value])

        current_base_tokens = header_tokens + hard_tokens + episodic_tokens
        remaining_budget = max(0, self.max_context_tokens - current_base_tokens)

        # Выделяем до 60% остатка на Brand DNA
        dna_budget = int(remaining_budget * 0.65) if remaining_budget > 0 else 0
        dna_items = layer_groups[DocCategoryEnum.BRAND_DNA.value]
        kept_dna: List[RetrievalResult] = []
        current_dna_tokens = 0
        for r in dna_items:
            t = self._estimate_tokens(r.chunk.text)
            if current_dna_tokens + t <= dna_budget or not kept_dna:
                kept_dna.append(r)
                current_dna_tokens += t
            else:
                if DocCategoryEnum.BRAND_DNA.value not in truncated_layers:
                    truncated_layers.append(DocCategoryEnum.BRAND_DNA.value)

        layer_groups[DocCategoryEnum.BRAND_DNA.value] = kept_dna

        # Оставшийся бюджет отдаем Audience Priors и General
        audience_budget = max(0, remaining_budget - current_dna_tokens)
        audience_items = layer_groups[DocCategoryEnum.AUDIENCE_PRIORS.value]
        kept_audience: List[RetrievalResult] = []
        current_audience_tokens = 0
        for r in audience_items:
            t = self._estimate_tokens(r.chunk.text)
            if current_audience_tokens + t <= audience_budget:
                kept_audience.append(r)
                current_audience_tokens += t
            else:
                if DocCategoryEnum.AUDIENCE_PRIORS.value not in truncated_layers:
                    truncated_layers.append(DocCategoryEnum.AUDIENCE_PRIORS.value)

        layer_groups[DocCategoryEnum.AUDIENCE_PRIORS.value] = kept_audience

        # 4. Формирование структурированного текстового контекста
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
        final_chunks: List[Chunk] = []

        for layer_key in ordered_layers:
            items = layer_groups[layer_key]
            if not items:
                continue

            section_header = self.LAYER_TITLES.get(layer_key, f"=== СЛОЙ: {layer_key.upper()} ===")
            chunk_blocks = []
            for res in items:
                chunk = res.chunk
                final_chunks.append(chunk)
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
        total_tokens = self._estimate_tokens(formatted_context_str)

        stratified_dict = {
            DocCategoryEnum.HARD_FACT.value: [r.chunk for r in layer_groups[DocCategoryEnum.HARD_FACT.value]],
            DocCategoryEnum.BRAND_DNA.value: [r.chunk for r in layer_groups[DocCategoryEnum.BRAND_DNA.value]],
            DocCategoryEnum.AUDIENCE_PRIORS.value: [r.chunk for r in layer_groups[DocCategoryEnum.AUDIENCE_PRIORS.value]],
            DocCategoryEnum.EPISODIC_MEMORY.value: [r.chunk for r in layer_groups[DocCategoryEnum.EPISODIC_MEMORY.value]],
        }

        return RAGContext(
            query=query,
            formatted_context=formatted_context_str.strip(),
            chunks=final_chunks,
            top_score=top_score,
            has_sufficient_context=True,
            fallback_message=None,
            stratified_layers=stratified_dict,
            total_tokens=total_tokens,
            is_truncated=bool(truncated_layers),
            truncated_layers=truncated_layers
        )

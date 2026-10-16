"""
Модели данных для Clean RAG подсистемы UCust.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum


class DocCategoryEnum(str, Enum):
    """4 фундаментальных слоя знаний RAG-пайплайна."""
    HARD_FACT = "hard_fact"                # 1. Жёсткие факты (цены, составы, габариты, гарантии, адреса)
    BRAND_DNA = "brand_dna"                # 2. ДНК бренда (ToV, редполитика, эталоны, контрасты ❌/✅)
    AUDIENCE_PRIORS = "audience_priors"    # 3. Боли и потребности ЦА (триггеры, FAQ, возражения)
    EPISODIC_MEMORY = "episodic_memory"    # 4. Эпизодическая память (директивы, прошлые правки, стоп-слова)


class TrustTierEnum(str, Enum):
    """Уровень верификации чанка в RAG."""
    VERIFIED_BY_OWNER = "verified_by_owner"    # 100% подтверждено владельцем / документами
    VERIFIED_AUTOMATED = "verified_automated"  # Извлечено веб-скрапером / OCR
    INFERRED_NICHE = "inferred_niche"          # Автодополнено из онтологии ниши
    SYSTEM_DIRECTIVE = "system_directive"      # Системное указание / правка модератора


class PlatformTargetEnum(str, Enum):
    """Целевая платформа публикации для контента."""
    ALL = "all"
    TELEGRAM = "telegram"
    VK = "vk"
    OK = "ok"


@dataclass
class Document:
    """Сырой входной документ (пост, статья базы знаний, отзыв)."""
    doc_id: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    source: str = "unknown"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class Chunk:
    """Семантический чанк документа, подготовленный для индексации."""
    chunk_id: str
    doc_id: str
    text: str
    token_count: int
    metadata: Dict[str, Any] = field(default_factory=dict)
    source: str = "unknown"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    @property
    def doc_category(self) -> str:
        return self.metadata.get("doc_category") or self.metadata.get("category") or "general"

    @property
    def trust_tier(self) -> str:
        return self.metadata.get("trust_tier") or TrustTierEnum.VERIFIED_AUTOMATED.value

    @property
    def platform_target(self) -> str:
        return self.metadata.get("platform_target") or PlatformTargetEnum.ALL.value

    @property
    def tenant_id(self) -> Optional[str]:
        return self.metadata.get("tenant_id") or self.metadata.get("client_id")


@dataclass
class RetrievalResult:
    """Результат поиска с оценками релевантности."""
    chunk: Chunk
    dense_score: float = 0.0
    sparse_score: float = 0.0
    hybrid_score: float = 0.0
    rerank_score: float = 0.0


@dataclass
class RAGContext:
    """Финальный упакованный контекст для передачи в генеративную модель (Сайгу)."""
    query: str
    formatted_context: str
    chunks: List[Chunk]
    top_score: float
    has_sufficient_context: bool
    fallback_message: Optional[str] = None
    stratified_layers: Optional[Dict[str, List[Chunk]]] = None
    total_tokens: int = 0
    is_truncated: bool = False
    truncated_layers: List[str] = field(default_factory=list)

    def get_layer(self, layer_name: str) -> List[Chunk]:
        """Возвращает чанки указанного слоя (hard_fact, brand_dna, audience_priors, episodic_memory)."""
        if not self.stratified_layers:
            return []
        return self.stratified_layers.get(layer_name, [])

    @property
    def has_hard_facts(self) -> bool:
        """Проверяет наличие проверенных фактов в Hard Ground Truth слое."""
        return len(self.get_layer(DocCategoryEnum.HARD_FACT.value)) > 0


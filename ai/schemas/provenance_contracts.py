"""
File: ai/schemas/provenance_contracts.py
Строгие Pydantic v2 контракты для архитектурного паттерна
Metadata Provenance и Tiered Slot Filling в UCust.AI.

Разделяет атрибуты и знания бренда на три фундаментальные категории:
1. Hard Facts (Жёсткие коммерческие факты): цены, сроки, гарантии, адреса, телефоны.
   Категорически запрещено выдумывать. При отсутствии помечаются как MISSING с безопасным Fallback CTA.
2. Soft Attributes (Бренд и контекст): боли аудитории, ToV, архетип, визуальные пропсы.
   Автодополняются через базу отраслевых онтологий (Niche Priors) с пометкой is_inferred=True.
3. Dynamic Fields (Неизвестные специфичные поля): кастомные характеристики («обжарка», «СРО»).
   Сохраняются в открытый контейнер динамических атрибутов (PostgreSQL JSONB).
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class FieldCategoryEnum(str, Enum):
    """Категория поля по степени допустимости синтеза/инференса."""
    HARD_FACT = "hard_fact"          # Цены, скидки, сроки доставки, гарантия, адреса, контакты
    SOFT_ATTRIBUTE = "soft_attribute" # Боли ЦА, ToV, архетип бренда, визуальные пропсы, УТП
    DYNAMIC_FIELD = "dynamic_field"   # Специфичные кастомные свойства (обжарка, класс арматуры и т.д.)


class FieldProvenanceEnum(str, Enum):
    """Источник происхождения значения атрибута (Data Provenance)."""
    EXTRACTED = "extracted"                       # 100% подтвержденный факт из сайта/документа/канала
    INFERRED_NICHE_PRIOR = "inferred_niche_prior" # Автодополнено из отраслевой онтологии (Niche Prior)
    INFERRED_LLM = "inferred_llm"                 # Сгенерировано LLM на базе контекста
    DEFAULT_FALLBACK = "default_fallback"         # Базовый системный дефолт
    MISSING = "missing"                           # Отсутствует, запрещено придумывать цифры


class FallbackStrategyEnum(str, Enum):
    """Безопасная стратегия призыва к действию (CTA) при отсутствии факта."""
    NONE = "none"
    CTA_TO_DM = "cta_to_dm"                         # «Уточняйте в сообщениях / директ»
    PRICE_ON_REQUEST = "price_on_request"           # «Прайс и расчет стоимости по запросу»
    BOOK_CONSULTATION = "book_consultation"         # «Запишитесь на консультацию»
    MICRO_INTERROGATION = "micro_interrogation"     # «Сформировать микро-вопрос пользователю»
    OMIT_FROM_COPY = "omit_from_copy"               # «Не упоминать данный аспект в посте»


class InferredFieldSchema(BaseModel):
    """
    Канонический контракт поля с метаданными происхождения и уровнем доверия.
    Устраняет синдром «плоских полей» в БД и RAG.
    """
    name: str = Field(..., description="Машиночитаемый идентификатор слота (например, pricing_model)")
    display_name: str = Field(..., description="Человекочитаемое название поля на русском языке")
    category: FieldCategoryEnum = Field(..., description="hard_fact | soft_attribute | dynamic_field")
    value: Optional[Any] = Field(None, description="Значение поля (строка, список, словарь или None)")
    source: FieldProvenanceEnum = Field(default=FieldProvenanceEnum.EXTRACTED, description="Происхождение данных")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Уровень достоверности: 1.0=факт, 0.75-0.85=prior, 0.0=missing")
    is_inferred: bool = Field(default=False, description="True, если поле достроено системой, а не извлечено из оригинала")
    fallback_strategy: Optional[FallbackStrategyEnum] = Field(None, description="Безопасная стратегия CTA при missing hard facts")
    evidence_quote: Optional[str] = Field(None, description="Точная цитата из текста-первоисточника, подтверждающая факт")
    niche_prior_applied: Optional[str] = Field(None, description="Название нишевого правила, использованного для автодополнения")
    user_prompt_suggestion: Optional[str] = Field(None, description="Микро-вопрос для онбординг-интерфейса, если факт критичен")
    extracted_at: datetime = Field(default_factory=datetime.utcnow, description="Время фиксации атрибута")


class TieredBrandDossier(BaseModel):
    """
    Структурированное досье бренда с многоуровневой классификацией слотов,
    готовое для сохранения в PostgreSQL JSONB, передачи на фронтенд и векторизации в RAG.
    """
    company_name: str = Field(..., description="Название компании/бренда")
    niche: str = Field(..., description="Сфера деятельности (например, 'кофейня', 'юридические услуги')")
    city: Optional[str] = Field(default="Москва", description="Город присутствия")
    
    # 3 фундаментальные категории полей
    hard_facts: Dict[str, InferredFieldSchema] = Field(
        default_factory=dict,
        description="Жёсткие факты (цены, скидки, гарантии, сроки, контакты, адреса)"
    )
    soft_attributes: Dict[str, InferredFieldSchema] = Field(
        default_factory=dict,
        description="Контекст и бренд (ToV, боли ЦА, архетип, визуальные пропсы, УТП)"
    )
    dynamic_attributes: Dict[str, InferredFieldSchema] = Field(
        default_factory=dict,
        description="Неизвестные специфичные характеристики ниши (PostgreSQL JSONB extensible)"
    )

    data_richness_score: int = Field(default=0, ge=0, le=100, description="Оценка плотности фактуры DRS (0-100)")
    drs_tier: str = Field(default="red", description="green | yellow | red")
    missing_hard_slots: List[str] = Field(default_factory=list, description="Список незаполненных обязательных жестких слотов")
    reverse_interrogation_questions: List[str] = Field(default_factory=list, description="Точечные микро-вопросы для UI")
    rag_grounded_facts: List[str] = Field(default_factory=list, description="Форматированные факты для индексации в Clean RAG")

    def to_prefilled_profile(self) -> Dict[str, Any]:
        """
        Формирует канонический prefilled_profile для фронтенд-онбординга и сохранения в UserProfile.
        """
        contacts_dict: Dict[str, List[str]] = {"phones": [], "emails": []}
        if "phones" in self.hard_facts and self.hard_facts["phones"].value:
            contacts_dict["phones"] = self.hard_facts["phones"].value if isinstance(self.hard_facts["phones"].value, list) else [str(self.hard_facts["phones"].value)]
        if "emails" in self.hard_facts and self.hard_facts["emails"].value:
            contacts_dict["emails"] = self.hard_facts["emails"].value if isinstance(self.hard_facts["emails"].value, list) else [str(self.hard_facts["emails"].value)]

        tov = self.soft_attributes.get("tone_of_voice")
        tov_str = tov.value if (tov and tov.value) else "Уверенный, лаконичный, экспертный"

        pains = self.soft_attributes.get("pain_points")
        pains_list = pains.value if (pains and isinstance(pains.value, list)) else []

        usp = self.soft_attributes.get("key_usp")
        usp_list = usp.value if (usp and isinstance(usp.value, list)) else []

        return {
            "business_name": self.company_name,
            "niche": self.niche,
            "city": self.city or "Москва",
            "tone_of_voice": tov_str,
            "target_audience_pains": pains_list,
            "key_usp": usp_list,
            "contacts": contacts_dict,
            "data_richness_score": self.data_richness_score,
            "drs_tier": self.drs_tier,
            "missing_slots": self.missing_hard_slots,
            "reverse_interrogation_questions": self.reverse_interrogation_questions,
            "provenance_metadata": {
                "hard_facts_count": len(self.hard_facts),
                "soft_attributes_count": len(self.soft_attributes),
                "dynamic_attributes_count": len(self.dynamic_attributes),
            }
        }

    def get_anti_hallucination_guardrails(self) -> str:
        """
        Генерирует строгие правила приземления (Truth Grounding) для LLM промптов CampaignService.
        """
        lines = [
            f"=== СТРОГИЕ ПРАВИЛА ПРИЗЕМЛЕНИЯ (TRUTH GROUNDING) ДЛЯ {self.company_name} ===",
            "1. ФАКТЫ О ЦЕНАХ И АКЦИЯХ:",
        ]
        
        pricing = self.hard_facts.get("pricing_model")
        if pricing and pricing.source == FieldProvenanceEnum.EXTRACTED and pricing.value:
            lines.append(f"   - Подтвержденные цены: {pricing.value}. Используй строго эти цифры.")
        else:
            lines.append("   - ⚠️ ТОЧНЫХ ЦЕН НЕТ. Категорически ЗАПРЕЩЕНО выдумывать рубли/скидки/проценты!")
            lines.append("   - Используй формулировки: 'Стоимость уточняйте в сообщениях', 'Напишите в директ для расчета', 'Прайс по запросу'.")

        terms = self.hard_facts.get("terms_guarantees")
        if terms and terms.source == FieldProvenanceEnum.EXTRACTED and terms.value:
            lines.append(f"2. СРОКИ И ГАРАНТИИ: подтверждены ({terms.value}).")
        else:
            lines.append("2. СРОКИ И ГАРАНТИИ: ⚠️ Точные гарантии не зафиксированы. Не давай обещаний '100% возврат за 24 часа'.")

        tov = self.soft_attributes.get("tone_of_voice")
        if tov and tov.value:
            lines.append(f"3. ТОН ОБЩЕНИЯ (Tone of Voice): {tov.value} (Источник: {tov.source.value}).")

        lines.append("4. ДИНАМИЧЕСКИЕ ОСОБЕННОСТИ БРЕНДА:")
        if self.dynamic_attributes:
            for k, fld in self.dynamic_attributes.items():
                if fld.value:
                    lines.append(f"   - {fld.display_name}: {fld.value}")
        else:
            lines.append("   - Специфические технические ограничения отсутствуют.")

        return "\n".join(lines)

"""
File: ai/skills/niche_priors.py
Движок отраслевых априорных знаний (Niche Priors Engine) и
Tiered Slot Filling для UCust.AI.

Осуществляет:
1. Выявление жестких фактов (Hard Facts) с фиксацией цитат-доказательств.
2. Безопасное автодополнение бренд-контекста (Soft Attributes) по отраслевой онтологии.
3. Извлечение кастомных специфичных свойств ниши (Dynamic Attributes).
4. Формирование Anti-Hallucination Guardrails для промптов CampaignService.
"""

from __future__ import annotations

import re
import logging
from typing import Dict, Any, List, Optional, Tuple

from schemas.provenance_contracts import (
    FieldCategoryEnum,
    FieldProvenanceEnum,
    FallbackStrategyEnum,
    InferredFieldSchema,
    TieredBrandDossier,
)
from skills.data_richness_engine import DataRichnessEngine, DRSTier

logger = logging.getLogger("NichePriorsEngine")


# База отраслевых априорных онтологий (Niche Priors)
NICHE_ONTOLOGIES: Dict[str, Dict[str, Any]] = {
    "coffee": {
        "keywords": ["кофе", "кофейн", "обжарк", "барист", "эспрессо", "капучино", "зерн", "coffee"],
        "display_name": "Кофейня / Спешелти кофе",
        "tone_of_voice": "Теплый, крафтовый, чувственный, открытый и дружелюбный",
        "pain_points": [
            "Утренний цейтнот и нехватка времени",
            "Низкое качество масс-маркет кофе в сетевых магазинах",
            "Отсутствие уютного пространства для работы с ноутбуком или встреч",
            "Однообразный ассортимент без авторских вкусов"
        ],
        "key_usp": [
            "Свежая локальная обжарка зерна specialty-класса",
            "Стабильность рецептуры и выверенный баланс вкуса",
            "Атмосферное пространство с заботой о каждой детали"
        ],
        "brand_props": [
            "rustic solid light oak counter",
            "emerald green ceramic cup with latte art",
            "warm morning sunrise light through glass"
        ],
        "fallback_cta": FallbackStrategyEnum.CTA_TO_DM,
        "dynamic_triggers": ["обжарка", "сорт", "арабика", "робуста", "ферментация", "высота", "ноты"]
    },
    "beauty": {
        "keywords": ["бьюти", "салон", "ногт", "маникюр", "педикюр", "косметол", "волос", "парикмахер", "ресниц", "брови"],
        "display_name": "Салон красоты / Бьюти-услуги",
        "tone_of_voice": "Эстетичный, вдохновляющий, заботливый, экспертный и деликатный",
        "pain_points": [
            "Недолговечное покрытие ногтей и сколы",
            "Опасения за стерильность инструментов и безопасность",
            "Сложно найти понимающего мастера с хорошим вкусом",
            "Долгое время процедуры без должного комфорта"
        ],
        "key_usp": [
            "Медицинская трехэтапная стерилизация и крафт-пакеты",
            "Премиальные гипоаллергенные материалы с гарантией носки",
            "Забота о времени клиента: параллельные услуги в 4 руки"
        ],
        "brand_props": [
            "cream cashmere knit fabric",
            "warm travertine stone surface",
            "minimalist gold details and clean natural light"
        ],
        "fallback_cta": FallbackStrategyEnum.BOOK_CONSULTATION,
        "dynamic_triggers": ["стерилизация", "гель-лак", "материал", "палитра", "гарантия носки", "время процедуры"]
    },
    "b2b": {
        "keywords": ["b2b", "юрист", "адвокат", "консалтинг", "бухгалтер", "аудит", "it", "разработк", "маркетинг", "saas", "автоматизац"],
        "display_name": "B2B услуги / Консалтинг / IT",
        "tone_of_voice": "Строгий, аналитический, доказательный, лаконичный и надежный",
        "pain_points": [
            "Срыв сроков и отсутствие прозрачной отчетности",
            "Слив бюджета без понятного измеримого ROI",
            "Человеческий фактор и ошибки в документации",
            "Сложность масштабирования без автоматизации рутины"
        ],
        "key_usp": [
            "Четкая фиксация SLA, этапов и ответственности в договоре",
            "Глубокая отраслевая экспертиза и проверенные бизнес-кейсы",
            "Ориентация на окупаемость и снижение операционных издержек"
        ],
        "brand_props": [
            "dark bog oak table",
            "graphite notebook with polished metallic pen",
            "minimalist architectural interior and structured diagrams"
        ],
        "fallback_cta": FallbackStrategyEnum.PRICE_ON_REQUEST,
        "dynamic_triggers": ["сро", "лицензия", "sla", "стек", "интеграция", "api", "договор", "nda"]
    },
    "fitness": {
        "keywords": ["фитнес", "спорт", "тренажер", "тренер", "зал", "растяжк", "йога", "кроссфит", "пилатес"],
        "display_name": "Фитнес / Спорт / Здоровье",
        "tone_of_voice": "Энергичный, мотивирующий, поддерживающий, дисциплинирующий",
        "pain_points": [
            "Потеря мотивации и брошенные тренировки",
            "Страх травм из-за неправильной техники выполнения",
            "Переполненные залы и очереди к снарядам",
            "Отсутствие персонального контроля питания и прогресса"
        ],
        "key_usp": [
            "Персональный трекинг результатов и адаптация нагрузок",
            "Сертифицированный тренерский штаб с профильным образованием",
            "Комфортное зонирование без очередей"
        ],
        "brand_props": [
            "matte black gym equipment with neon accents",
            "fresh dynamic lighting and athletic textures",
            "water bottle and clean workout space"
        ],
        "fallback_cta": FallbackStrategyEnum.BOOK_CONSULTATION,
        "dynamic_triggers": ["абонемент", "тренер", "программа", "сплит", "квалификация", "душ", "парковка"]
    },
    "general": {
        "keywords": [],
        "display_name": "Бизнес и коммерческие услуги",
        "tone_of_voice": "Экспертный, уверенный, клиентоориентированный и лаконичный",
        "pain_points": [
            "Потеря времени на поиск надежного подрядчика",
            "Переплаты за скрытые комиссии и некачественный сервис",
            "Отсутствие понятной поддержки после продажи"
        ],
        "key_usp": [
            "Предсказуемое качество и соблюдение сроков",
            "Индивидуальный подход к специфике каждого клиента",
            "Честное и прозрачное ценообразование"
        ],
        "brand_props": [
            "clean contemporary workspace",
            "warm natural daylight",
            "textured high-quality materials"
        ],
        "fallback_cta": FallbackStrategyEnum.CTA_TO_DM,
        "dynamic_triggers": ["гарантия", "сертификат", "характеристики", "доставка", "материал"]
    }
}


class NichePriorsEngine:
    """
    Интеллектуальный процессор разделения полей на Hard Facts, Soft Attributes и Dynamic Fields.
    """

    @classmethod
    def resolve_niche_key(cls, niche_raw: str) -> str:
        """Определяет ключ онтологии по текстовой строке ниши."""
        n_low = (niche_raw or "").lower()
        for k, ont in NICHE_ONTOLOGIES.items():
            if k == "general":
                continue
            for kw in ont["keywords"]:
                if kw in n_low:
                    return k
        return "general"

    @classmethod
    def build_tiered_dossier(
        cls,
        raw_text: str,
        company_name: str = "Клиент",
        niche: str = "Бизнес",
        city: str = "Москва",
        extra_meta: Optional[Dict[str, Any]] = None
    ) -> TieredBrandDossier:
        """
        Главный пайплайн:
        1. DRS сканирование текста.
        2. Извлечение Hard Facts (цены, сроки, контакты).
        3. Обогащение Soft Attributes через Niche Priors.
        4. Детекция неизвестных Dynamic Fields.
        5. Подготовка RAG фактов.
        """
        extra = extra_meta or {}
        niche_key = cls.resolve_niche_key(niche)
        ontology = NICHE_ONTOLOGIES.get(niche_key, NICHE_ONTOLOGIES["general"])

        # 1. Запуск DRS (Data Richness Score)
        drs = DataRichnessEngine.evaluate_text(raw_text, company_name=company_name)

        hard_facts: Dict[str, InferredFieldSchema] = {}
        soft_attributes: Dict[str, InferredFieldSchema] = {}
        dynamic_attributes: Dict[str, InferredFieldSchema] = {}
        missing_hard_slots: List[str] = []
        rag_facts: List[str] = []

        # --- A. ЖЕСТКИЕ ФАКТЫ (HARD FACTS) ---
        # 1. Цены и тарифы (Pricing Model)
        slot_price = drs.slots.get("pricing_model")
        if slot_price and slot_price.is_filled and slot_price.extracted_items:
            price_quote = ", ".join(slot_price.extracted_items)
            hard_facts["pricing_model"] = InferredFieldSchema(
                name="pricing_model",
                display_name="Цены и тарифы",
                category=FieldCategoryEnum.HARD_FACT,
                value=slot_price.extracted_items,
                source=FieldProvenanceEnum.EXTRACTED,
                confidence=1.0,
                is_inferred=False,
                evidence_quote=f"Найденные ценовые маркеры: {price_quote}"
            )
            rag_facts.append(f"[VERIFIED] {company_name} — Стоимость и тарифы: {price_quote}")
        else:
            fb = ontology.get("fallback_cta", FallbackStrategyEnum.PRICE_ON_REQUEST)
            hard_facts["pricing_model"] = InferredFieldSchema(
                name="pricing_model",
                display_name="Цены и тарифы",
                category=FieldCategoryEnum.HARD_FACT,
                value=None,
                source=FieldProvenanceEnum.MISSING,
                confidence=0.0,
                is_inferred=False,
                fallback_strategy=fb,
                user_prompt_suggestion=f"Укажите базовую стоимость услуг для «{company_name}» (например: 'от 3000 ₽')"
            )
            missing_hard_slots.append("pricing_model")

        # 2. Сроки и гарантии (Terms & Guarantees)
        slot_terms = drs.slots.get("terms_guarantees")
        if slot_terms and slot_terms.is_filled and slot_terms.extracted_items:
            terms_quote = ", ".join(slot_terms.extracted_items)
            hard_facts["terms_guarantees"] = InferredFieldSchema(
                name="terms_guarantees",
                display_name="Сроки и гарантии",
                category=FieldCategoryEnum.HARD_FACT,
                value=slot_terms.extracted_items,
                source=FieldProvenanceEnum.EXTRACTED,
                confidence=1.0,
                is_inferred=False,
                evidence_quote=f"Условия: {terms_quote}"
            )
            rag_facts.append(f"[VERIFIED] {company_name} — Сроки и гарантии: {terms_quote}")
        else:
            hard_facts["terms_guarantees"] = InferredFieldSchema(
                name="terms_guarantees",
                display_name="Сроки и гарантии",
                category=FieldCategoryEnum.HARD_FACT,
                value=None,
                source=FieldProvenanceEnum.MISSING,
                confidence=0.0,
                is_inferred=False,
                fallback_strategy=FallbackStrategyEnum.CTA_TO_DM,
                user_prompt_suggestion=f"Укажите реальные сроки доставки или гарантию для «{company_name}»"
            )
            missing_hard_slots.append("terms_guarantees")

        # 3. Контакты (Телефоны / Emails)
        phone_matches = re.findall(r'(?:\+7|8)[\s\-\(]*\d{3}[\s\-\)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}', raw_text)
        email_matches = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', raw_text)

        if phone_matches:
            hard_facts["phones"] = InferredFieldSchema(
                name="phones",
                display_name="Контактные телефоны",
                category=FieldCategoryEnum.HARD_FACT,
                value=list(set(phone_matches))[:3],
                source=FieldProvenanceEnum.EXTRACTED,
                confidence=1.0,
                is_inferred=False
            )
        if email_matches:
            hard_facts["emails"] = InferredFieldSchema(
                name="emails",
                display_name="Электронная почта",
                category=FieldCategoryEnum.HARD_FACT,
                value=list(set(email_matches))[:2],
                source=FieldProvenanceEnum.EXTRACTED,
                confidence=1.0,
                is_inferred=False
            )

        # --- B. МЯГКИЕ АТРИБУТЫ (SOFT ATTRIBUTES / BRAND CONTEXT) ---
        # 1. Тон коммуникации (Tone of Voice)
        tov_val = extra.get("tone_of_voice") or ontology["tone_of_voice"]
        soft_attributes["tone_of_voice"] = InferredFieldSchema(
            name="tone_of_voice",
            display_name="Тон коммуникации (ToV)",
            category=FieldCategoryEnum.SOFT_ATTRIBUTE,
            value=tov_val,
            source=FieldProvenanceEnum.INFERRED_NICHE_PRIOR if not extra.get("tone_of_voice") else FieldProvenanceEnum.EXTRACTED,
            confidence=0.85 if not extra.get("tone_of_voice") else 1.0,
            is_inferred=not bool(extra.get("tone_of_voice")),
            niche_prior_applied=ontology["display_name"]
        )
        rag_facts.append(f"[NICHE_PRIOR] Стиль и ToV для {company_name}: {tov_val}")

        # 2. Боли целевой аудитории (Pain Points)
        slot_pain = drs.slots.get("pain_points")
        if slot_pain and slot_pain.is_filled and len(slot_pain.extracted_items) >= 2:
            soft_attributes["pain_points"] = InferredFieldSchema(
                name="pain_points",
                display_name="Боли целевой аудитории",
                category=FieldCategoryEnum.SOFT_ATTRIBUTE,
                value=slot_pain.extracted_items,
                source=FieldProvenanceEnum.EXTRACTED,
                confidence=0.95,
                is_inferred=False
            )
            rag_facts.append(f"[VERIFIED] Боли ЦА {company_name}: {', '.join(slot_pain.extracted_items)}")
        else:
            inferred_pains = ontology["pain_points"]
            soft_attributes["pain_points"] = InferredFieldSchema(
                name="pain_points",
                display_name="Боли целевой аудитории",
                category=FieldCategoryEnum.SOFT_ATTRIBUTE,
                value=inferred_pains,
                source=FieldProvenanceEnum.INFERRED_NICHE_PRIOR,
                confidence=0.80,
                is_inferred=True,
                niche_prior_applied=ontology["display_name"]
            )
            rag_facts.append(f"[NICHE_PRIOR] Отраслевые боли клиентов {niche}: {'; '.join(inferred_pains[:3])}")

        # 3. Ключевые УТП (Key USP)
        slot_features = drs.slots.get("product_features")
        if slot_features and slot_features.is_filled and slot_features.extracted_items:
            usp_val = [f"Преимущество продукта: {item}" for item in slot_features.extracted_items[:3]]
            soft_attributes["key_usp"] = InferredFieldSchema(
                name="key_usp",
                display_name="Уникальное торговое предложение",
                category=FieldCategoryEnum.SOFT_ATTRIBUTE,
                value=usp_val,
                source=FieldProvenanceEnum.EXTRACTED,
                confidence=0.95,
                is_inferred=False
            )
        else:
            usp_val = [f"{u} (для {company_name})" for u in ontology["key_usp"]]
            soft_attributes["key_usp"] = InferredFieldSchema(
                name="key_usp",
                display_name="Уникальное торговое предложение",
                category=FieldCategoryEnum.SOFT_ATTRIBUTE,
                value=usp_val,
                source=FieldProvenanceEnum.INFERRED_NICHE_PRIOR,
                confidence=0.75,
                is_inferred=True,
                niche_prior_applied=ontology["display_name"]
            )

        # 4. Визуальные пропсы для фото/генерации
        soft_attributes["visual_props"] = InferredFieldSchema(
            name="visual_props",
            display_name="Визуальные атрибуты и пропсы",
            category=FieldCategoryEnum.SOFT_ATTRIBUTE,
            value=ontology["brand_props"],
            source=FieldProvenanceEnum.INFERRED_NICHE_PRIOR,
            confidence=0.85,
            is_inferred=True,
            niche_prior_applied=ontology["display_name"]
        )

        # --- C. НЕИЗВЕСТНЫЕ СПЕЦИФИЧНЫЕ ПОЛЯ (DYNAMIC FIELDS) ---
        triggers = ontology.get("dynamic_triggers", [])
        for trig in triggers:
            # Ищем предложения или фрагменты с данным ключевым словом
            pattern = rf'([^.\n]*\b{re.escape(trig)}[a-яA-Я0-9\s\-_–—:%]{{3,80}}[^.\n]*)'
            matches = re.findall(pattern, raw_text, re.IGNORECASE)
            if matches:
                clean_frag = matches[0].strip()
                if len(clean_frag) > 10:
                    field_key = f"dyn_{trig}"
                    dynamic_attributes[field_key] = InferredFieldSchema(
                        name=field_key,
                        display_name=f"Специфика: {trig.capitalize()}",
                        category=FieldCategoryEnum.DYNAMIC_FIELD,
                        value=clean_frag,
                        source=FieldProvenanceEnum.EXTRACTED,
                        confidence=0.90,
                        is_inferred=False,
                        evidence_quote=clean_frag
                    )
                    rag_facts.append(f"[VERIFIED] {company_name} — Особенность ({trig}): {clean_frag}")

        return TieredBrandDossier(
            company_name=company_name,
            niche=niche,
            city=city,
            hard_facts=hard_facts,
            soft_attributes=soft_attributes,
            dynamic_attributes=dynamic_attributes,
            data_richness_score=drs.total_score,
            drs_tier=drs.tier.value,
            missing_hard_slots=missing_hard_slots,
            reverse_interrogation_questions=drs.reverse_interrogation_questions,
            rag_grounded_facts=rag_facts
        )


__all__ = ["NichePriorsEngine", "NICHE_ONTOLOGIES"]

# File: skills/context_router.py
"""
ContextRouterSkill & RoutingDirective Engine for UCust.AI.
Pre-Flight Classifier & Payload-Driven Directive Generator.
"""

from __future__ import annotations

import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import re
import json
import logging
from enum import Enum
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("context_router")


class QuadrantEnum(str, Enum):
    B2B_TECH = "B2B_TECH"          # IT, SaaS, AI, Hardware, Cloud, Dev, IoT
    B2B_SERVICE = "B2B_SERVICE"    # B2B Консалтинг, Юристы, Бухгалтерия, Логистика
    B2C_ECOM = "B2C_ECOM"          # Товары, Одежда, Мебель, Техника, Еда на вынос
    B2C_LIFESTYLE = "B2C_LIFESTYLE"# Кофейни, Питомцы, Красота, Фитнес, Культура, Религия


class IntentModeEnum(str, Enum):
    CORE_BUSINESS = "CORE_BUSINESS"                # Прямой профильный пост компании
    LIFESTYLE_CROSSOVER = "LIFESTYLE_CROSSOVER"    # Мост / Лайфстайл (напр. IT + кофе/кот)
    HUMOR_METAPHOR = "HUMOR_METAPHOR"              # Юмор, мемы, профессиональная самоирония
    HOLIDAY_SEASONAL = "HOLIDAY_SEASONAL"          # Праздники, государственные и сезонные даты


class FunnelLockEnum(str, Enum):
    TOFU_UNAWARE = "TOFU_UNAWARE"      # Вовлечение, охват, разрушение мифов (без жестких продаж)
    MOFU_SOLUTION = "MOFU_SOLUTION"    # Прогрев, экспертность, разбор кейсов, технологии
    BOFU_MOST_AWARE = "BOFU_MOST_AWARE"# Прямой оффер, спецпредложение, лид-магнит


class AllowedMetricsEnum(str, Enum):
    NONE = "none"                      # Никаких цифр и процентов (чистый лайфстайл)
    CONSUMER_ONLY = "consumer_only"    # Только бытовые цифры (цена, скидка 20%, время 15 мин)
    ENTERPRISE_ROI = "enterprise_roi"  # Бизнес-метрики (CAC, SLA 99.9%, конверсия, окупаемость)


class VisualAnchorDirective(BaseModel):
    environment_preset: str = "contemporary_bright_studio"
    lighting_preset: str = "natural_soft_window_daylight"
    lens_and_angle: str = "35mm_candid_eye_level"
    crossover_props: str = ""
    color_palette_harmony: str = "warm_analogous"
    camera_iso_aperture: str = "f/1.8, creamy background bokeh, ISO 100"


class CriticRulesDirective(BaseModel):
    semantic_bleed_check_required: bool = False
    max_percentages_allowed: int = 1
    forbidden_regex: List[str] = Field(default_factory=list)
    oxymoron_guard_prompt: str = ""


class TextGenerationDirective(BaseModel):
    tone_archetype: str = "founder_expert"
    funnel_lock: FunnelLockEnum = FunnelLockEnum.TOFU_UNAWARE
    forced_framework: str = "BAB"
    allowed_metrics: AllowedMetricsEnum = AllowedMetricsEnum.CONSUMER_ONLY
    forbidden_categories: List[str] = Field(default_factory=list)
    narrative_bridge: Optional[str] = None


class RoutingDirective(BaseModel):
    """
    Единая типизированная директива (Single Source of Truth),
    управляющая SaigaLLM, CriticMunger, ComfyUI и RAG.
    """
    tenant_id: str = "default_tenant"
    quadrant: QuadrantEnum = QuadrantEnum.B2B_TECH
    intent_mode: IntentModeEnum = IntentModeEnum.CORE_BUSINESS
    brand_integration_level: str = "high"  # high | medium | low | none
    confidence_score: float = 0.95
    detected_subject: str = ""
    text_directive: TextGenerationDirective = Field(default_factory=TextGenerationDirective)
    critic_directive: CriticRulesDirective = Field(default_factory=CriticRulesDirective)
    visual_anchor: VisualAnchorDirective = Field(default_factory=VisualAnchorDirective)

    @classmethod
    def safe_fallback(cls, topic: str, company_name: str = "UCust", niche: str = "Martech", tenant_id: str = "default_tenant") -> "RoutingDirective":
        """
        Pydantic Safe Default: Гарантированный возврат согласованного объекта
        при синтаксических ошибках или таймаутах внешних LLM.
        """
        topic_low = (topic or "").lower()
        niche_low = (niche or "").lower()
        
        is_lifestyle = any(w in topic_low for w in ["кофе", "раф", "кот", "собак", "питом", "еда", "ресторан", "церков", "религ", "праздник", "чай", "кухн"])
        is_ecom = any(w in topic_low for w in ["плать", "одежд", "доставк", "товар", "каталог", "размер", "примерк", "куртк", "обув"])
        
        if is_lifestyle:
            quadrant = QuadrantEnum.B2C_LIFESTYLE
            intent_mode = IntentModeEnum.LIFESTYLE_CROSSOVER if any(w in niche_low for w in ["it", "saas", "ai", "soft", "tech", "маркетинг"]) else IntentModeEnum.CORE_BUSINESS
            funnel_lock = FunnelLockEnum.TOFU_UNAWARE
            allowed_metrics = AllowedMetricsEnum.CONSUMER_ONLY
            forbidden = ["hard_b2b_roi", "corporate_cliches", "drastic_promises"]
            env = "cozy_warm_interior_with_soft_sunlight"
            props = "natural everyday lifestyle aesthetic"
        elif is_ecom:
            quadrant = QuadrantEnum.B2C_ECOM
            intent_mode = IntentModeEnum.CORE_BUSINESS
            funnel_lock = FunnelLockEnum.MOFU_SOLUTION
            allowed_metrics = AllowedMetricsEnum.CONSUMER_ONLY
            forbidden = ["hard_b2b_roi", "corporate_cliches"]
            env = "modern_clean_ecom_showroom"
            props = "tactile materials and handcrafted craftsmanship"
        else:
            quadrant = QuadrantEnum.B2B_TECH
            intent_mode = IntentModeEnum.CORE_BUSINESS
            funnel_lock = FunnelLockEnum.MOFU_SOLUTION
            allowed_metrics = AllowedMetricsEnum.ENTERPRISE_ROI
            forbidden = ["corporate_cliches", "drastic_promises"]
            env = "sleek_contemporary_tech_office"
            props = "ultra-thin laptop with clean analytics interface"

        return cls(
            tenant_id=tenant_id or company_name.lower().replace(" ", "_"),
            quadrant=quadrant,
            intent_mode=intent_mode,
            brand_integration_level="medium" if intent_mode == IntentModeEnum.LIFESTYLE_CROSSOVER else "high",
            confidence_score=0.85,
            detected_subject=topic[:80],
            text_directive=TextGenerationDirective(
                tone_archetype="founder_lifestyle" if is_lifestyle else "founder_expert",
                funnel_lock=funnel_lock,
                forced_framework="StoryBrand" if is_lifestyle else "PAS",
                allowed_metrics=allowed_metrics,
                forbidden_categories=forbidden
            ),
            critic_directive=CriticRulesDirective(
                semantic_bleed_check_required=is_lifestyle,
                max_percentages_allowed=0 if is_lifestyle else 2,
                forbidden_regex=[
                    r"оптимиз\w+", r"\bkpi\b", r"\broi\b", r"документооборот\w*",
                    r"сокращени\w+ издержек", r"бюджет на религиозн\w+", r"внедрени\w+ под ключ"
                ] if is_lifestyle else [],
                oxymoron_guard_prompt="Проверь, нет ли смешения B2B метрик с бытовой темой."
            ),
            visual_anchor=VisualAnchorDirective(
                environment_preset=env,
                crossover_props=props
            )
        )


class ContextRouterSkill:
    """
    Интеллектуальный Pre-Flight роутер UCust.AI:
    Выполняет микро-классификацию намерения, исключает разрыв контекста (Context Collapse)
    и формирует согласованную RoutingDirective до инференса тяжелых генераторов.
    """

    QUADRANT_PATTERNS = {
        QuadrantEnum.B2B_TECH: [
            "saas", "rag", "llm", "ai", "ии", "нейросеть", "платформ", "автоматизац",
            "api", "софт", "сервер", "код", "разработк", "интеграц", "martech", "iot",
            "плата", "esp32", "микроконтроллер", "схемотехник", "инфраструктур", "облак"
        ],
        QuadrantEnum.B2B_SERVICE: [
            "бухгалтер", "юрист", "аудит", "консалтинг", "логистик", "грузоперевоз",
            "b2b", "тендер", "договор", "коммерческ", "поставк", "аутсорсинг", "аренд"
        ],
        QuadrantEnum.B2C_ECOM: [
            "одежд", "плать", "обув", "мебел", "диван", "стол из дуба", "доставк за 3 дня",
            "примерк", "размер", "каталог", "скидк", "товар", "интернет-магазин", "бренд"
        ],
        QuadrantEnum.B2C_LIFESTYLE: [
            "кофе", "раф", "капучино", "латте", "десерт", "круассан", "выпечк", "ресторан",
            "кот", "кошк", "собак", "питом", "клиник", "массаж", "spa", "маникюр",
            "бьюти", "фитнес", "тренировк", "спортзал", "церков", "храм", "праздник", "уют"
        ]
    }

    CROSSOVER_LIFESTYLE_TRIGGERS = [
        "кот", "кош", "собак", "питом", "кофе", "раф", "чай", "утро", "завтрак",
        "кухн", "пятниц", "выходн", "отдых", "спорт", "прогулк", "праздник", "елка"
    ]

    def __init__(self, llm_engine=None):
        self.llm = llm_engine

    def route_task(
        self,
        topic: str,
        company_name: str = "UCust",
        niche: str = "Martech",
        user_data: Optional[Dict[str, Any]] = None
    ) -> RoutingDirective:
        tenant_id = (user_data or {}).get("tenant_id") or (user_data or {}).get("user_id") or company_name.lower().replace(" ", "_")
        
        try:
            topic_clean = (topic or "").strip()
            topic_lower = topic_clean.lower()
            niche_lower = (niche or "").lower()
            company_lower = (company_name or "").lower()

            detected_quadrant = self._classify_quadrant(topic_lower, niche_lower)
            is_company_tech = any(k in (niche_lower + " " + company_lower) for k in ["it", "saas", "ai", "soft", "tech", "маркетинг", "martech", "автоматизац"])
            has_lifestyle_subject = any(t in topic_lower for t in self.CROSSOVER_LIFESTYLE_TRIGGERS)

            if is_company_tech and has_lifestyle_subject:
                intent_mode = IntentModeEnum.LIFESTYLE_CROSSOVER
                brand_integration = "medium"
                funnel_lock = FunnelLockEnum.TOFU_UNAWARE
                allowed_metrics = AllowedMetricsEnum.CONSUMER_ONLY
                tone = "founder_lifestyle"
                framework = "BAB"
                forbidden = ["hard_b2b_roi", "corporate_cliches", "drastic_promises"]
                bleed_check = True
                
                if any(w in topic_lower for w in ["кот", "кошк", "собак", "питом"]):
                    env_preset = "modern_sunlit_it_office_loft"
                    props = "adorable friendly domestic cat resting comfortably near a sleek open laptop with code and coffee mug"
                elif any(w in topic_lower for w in ["кофе", "раф", "чай", "напиток"]):
                    env_preset = "bright_contemporary_tech_startup_lounge"
                    props = "ceramic coffee mug on warm oak desk next to thin aluminum laptop and lush indoor office plant"
                else:
                    env_preset = "bright_minimalist_open_plan_studio"
                    props = "warm authentic team workspace atmosphere"

            elif detected_quadrant == QuadrantEnum.B2C_LIFESTYLE:
                intent_mode = IntentModeEnum.CORE_BUSINESS
                brand_integration = "high"
                funnel_lock = FunnelLockEnum.TOFU_UNAWARE if any(w in topic_lower for w in ["атмосфер", "уют", "религ", "церков", "мем", "праздник", "юмор", "кот", "кошк", "собак"]) else FunnelLockEnum.MOFU_SOLUTION
                allowed_metrics = AllowedMetricsEnum.CONSUMER_ONLY
                tone = "warm_hospitable"
                framework = "StoryBrand"
                forbidden = ["hard_b2b_roi", "corporate_cliches", "drastic_promises"]
                bleed_check = True
                
                if any(w in topic_lower for w in ["кофе", "раф", "десерт", "пекарн", "ресторан"]):
                    env_preset = "artisan_craft_coffee_bar_sunlit_window"
                    props = "ceramic cup with delicate latte art, flaky pastry on ceramic plate, warm morning bokeh"
                elif any(w in topic_lower for w in ["церков", "храм", "религ"]):
                    env_preset = "historic_peaceful_cathedral_interior"
                    props = "serene architectural arches, soft natural candle glow and stained glass reflections"
                else:
                    env_preset = "warm_cozy_living_space"
                    props = "natural soft fabrics and organic daylight"

            elif detected_quadrant == QuadrantEnum.B2C_ECOM:
                intent_mode = IntentModeEnum.CORE_BUSINESS
                brand_integration = "high"
                funnel_lock = FunnelLockEnum.MOFU_SOLUTION
                allowed_metrics = AllowedMetricsEnum.CONSUMER_ONLY
                tone = "aesthetic_product_curator"
                framework = "FAB"
                forbidden = ["hard_b2b_roi", "corporate_cliches"]
                bleed_check = False
                env_preset = "minimalist_scandinavian_design_showroom"
                props = "tactile textures, natural wood, premium materials and authentic craftsmanship"

            else:
                intent_mode = IntentModeEnum.CORE_BUSINESS
                brand_integration = "high"
                funnel_lock = FunnelLockEnum.MOFU_SOLUTION
                allowed_metrics = AllowedMetricsEnum.ENTERPRISE_ROI
                tone = "founder_expert"
                framework = "PAS"
                forbidden = ["corporate_cliches", "drastic_promises"]
                bleed_check = False
                env_preset = "sleek_contemporary_tech_headquarters"
                props = "ultra-thin laptop displaying glowing analytics charts and clean modern workspace"

            forbidden_regex = []
            if bleed_check or detected_quadrant in [QuadrantEnum.B2C_LIFESTYLE, QuadrantEnum.B2C_ECOM]:
                forbidden_regex = [
                    r"оптимиз\w+",
                    r"\bkpi\b",
                    r"\broi\b",
                    r"документооборот\w*",
                    r"сокращени\w+ издержек",
                    r"бюджет на религиозн\w+",
                    r"внедрени\w+ под ключ",
                    r"сертификат\w+ и справк\w+ вдвое быстр\w+"
                ]

            is_lifestyle_env = (detected_quadrant == QuadrantEnum.B2C_LIFESTYLE or has_lifestyle_subject)
            directive = RoutingDirective(
                tenant_id=tenant_id,
                quadrant=detected_quadrant,
                intent_mode=intent_mode,
                brand_integration_level=brand_integration,
                confidence_score=0.92,
                detected_subject=topic_clean[:100],
                text_directive=TextGenerationDirective(
                    tone_archetype=tone,
                    funnel_lock=funnel_lock,
                    forced_framework=framework,
                    allowed_metrics=allowed_metrics,
                    forbidden_categories=forbidden,
                    narrative_bridge=f"Органично раскрыть тему '{topic_clean}' в тональности {tone}."
                ),
                critic_directive=CriticRulesDirective(
                    semantic_bleed_check_required=bleed_check,
                    max_percentages_allowed=0 if (intent_mode == IntentModeEnum.LIFESTYLE_CROSSOVER or detected_quadrant == QuadrantEnum.B2C_LIFESTYLE) else 2,
                    forbidden_regex=forbidden_regex,
                    oxymoron_guard_prompt="Проверь, нет ли противоестественного смешения B2B-метрик с бытовой темой."
                ),
                visual_anchor=VisualAnchorDirective(
                    environment_preset=env_preset,
                    crossover_props=props,
                    lighting_preset="warm_morning_sunlight_through_window" if is_lifestyle_env else "soft_natural_diffused_daylight"
                )
            )
            return directive

        except Exception as e:
            logger.warning("[ContextRouterSkill] Exception: %s", e)
            return RoutingDirective.safe_fallback(topic=topic, company_name=company_name, niche=niche, tenant_id=tenant_id)

    def _classify_quadrant(self, topic: str, niche: str) -> QuadrantEnum:
        combined = f"{topic} {niche}".lower()
        scores = {q: 0 for q in QuadrantEnum}
        for quadrant, keywords in self.QUADRANT_PATTERNS.items():
            for kw in keywords:
                if kw in combined:
                    weight = 2 if kw in topic else 1
                    scores[quadrant] += weight
                    
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        if sorted_scores[0][1] > 0:
            return sorted_scores[0][0]
            
        if any(k in combined for k in ["it", "ai", "soft", "tech"]):
            return QuadrantEnum.B2B_TECH
        return QuadrantEnum.B2C_LIFESTYLE

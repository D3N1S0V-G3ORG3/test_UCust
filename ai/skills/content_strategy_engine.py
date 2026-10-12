"""
File: ai/skills/content_strategy_engine.py
Content Strategy & User Persona Engine for UCust AI.
Реализует динамическую драматургию по отраслям (B2C, B2B, Expert),
контроль тарифов (Tier-based access), разрешение семантических конфликтов (VLM vs RAG),
сжатие OCR-сущностей и генерацию черновиков DRAFT_TEXT (0 GPU overhead).
"""

from __future__ import annotations

import re
import uuid
import logging
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional

try:
    from core.lazy_rendering_controller import (
        SubscriptionTier,
        IndustryArchetype,
        ContentFormat,
        PostLifecycleStatus,
        ImageGenerationSpec,
        PostDraft,
        VRAMCostCalculator
    )
except ImportError:
    try:
        from ai.core.lazy_rendering_controller import (
            SubscriptionTier,
            IndustryArchetype,
            ContentFormat,
            PostLifecycleStatus,
            ImageGenerationSpec,
            PostDraft,
            VRAMCostCalculator
        )
    except ImportError:
        # Fallback Enums if imported standalone
        class SubscriptionTier(str, Enum):
            START = "start"
            BUSINESS = "business"
            CUSTOM = "custom"

            # Backward compatibility aliases
            STARTER = "start"
            PRO = "business"
            ENTERPRISE = "custom"

        class IndustryArchetype(str, Enum):
            B2C_LIFESTYLE = "b2c_lifestyle"
            B2B_CORPORATE = "b2b_corporate"
            EXPERT_SERVICES = "expert_services"

        class ContentFormat(str, Enum):
            SINGLE_SHOT = "single_shot"
            CAROUSEL_LIGHT = "carousel_light"
            CAROUSEL_HEAVY = "carousel_heavy"
            CRYPTEX_PUZZLE = "cryptex_puzzle"

        class PostLifecycleStatus(str, Enum):
            DRAFT_TEXT = "draft_text"
            AWAITING_RENDER = "awaiting_render"
            RENDERING = "rendering"
            RENDERED = "rendered"
            PUBLISHED = "published"
            FAILED = "failed"

from pydantic import BaseModel, Field

logger = logging.getLogger("ContentStrategyEngine")


class IngestionSourceType(str, Enum):
    USER_PHOTO = "user_photo"          # Фотография от пользователя (блюдо, цех, руки, товар)
    DOCUMENT_OCR = "document_ocr"      # Меню, прайс-лист, скан договора, сертификат
    RAG_FACTS_ONLY = "rag_facts_only"  # Генерация на основе базы знаний бренда без фото
    HYBRID = "hybrid"                  # Фото пользователя + RAG факты + Инфоповод


class BrandProfile(BaseModel):
    brand_id: str
    company_name: str
    industry: IndustryArchetype
    tier: SubscriptionTier
    brand_props: List[str] = Field(default_factory=list, description="RAG визуальные якоря (материалы, цвета, стиль)")
    tone_of_voice: str = Field(default="Уверенный, лаконичный, экспертный", description="Инструкции по тексту и стилю")


class RawDataIngestion(BaseModel):
    ingestion_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_type: IngestionSourceType = IngestionSourceType.HYBRID
    
    # Мультимодальные данные (Moondream2 / VLM)
    vlm_description: Optional[str] = Field(default=None, description="Сырое описание сцены от Moondream2")
    vlm_visual_anchors: List[str] = Field(default_factory=list, description="Извлеченные физические якоря")
    
    # Текстовое зрение (EasyOCR / OCR Engine)
    ocr_raw_text: Optional[str] = Field(default=None, description="Распознанный текст с изображения")
    
    # Контекст бренда (RAG & Knowledge Base)
    rag_context_snippets: List[str] = Field(default_factory=list, description="Релевантные факты о компании и УТП")
    
    # Календарный якорь и намерение пользователя
    calendar_event: Optional[str] = Field(default=None, description="Праздник или отраслевое событие")
    user_raw_intent: Optional[str] = Field(default=None, description="Прямое указание от пользователя")


# ==============================================================================
# 1. МАТРИЦА ДРАМАТУРГИИ ПО ОТРАСЛЯМ (ДИНАМИЧЕСКИЙ ToV)
# ==============================================================================

DRAMATURGY_MATRIX: Dict[IndustryArchetype, Dict[str, str]] = {
    IndustryArchetype.B2C_LIFESTYLE: {
        "MON": "Эмоция, сенсорика, эстетика, легкий муд. Запуск энергии недели.",
        "TUE": "Сенсорика продукта (вкус, текстура, материалы, тактильность).",
        "WED": "Атмосфера заведения, закулисье команды, детали интерьера.",
        "THU": "UGC, социальное доказательство, отзывы гостей.",
        "FRI": "Пятничный релакс, планы на выходные. Закрытый CTA (опрос/ссылка).",
        "WEEKEND": "Эстетичный лайфстайл-кадр без прямой агрессивной продажи."
    },
    IndustryArchetype.B2B_CORPORATE: {
        "MON": "Анализ рынка, стандарты, регуляторика, сводка недельных трендов.",
        "TUE": "Технологический процесс: контроль качества, этапы производства, M&A.",
        "WED": "Кейс внедрения: измеримые цифры (ROI, сокращение сроков, аудит).",
        "THU": "Разбор рисков: как не потерять бюджет при выборе подрядчика.",
        "FRI": "Итоги недели в отрасли: экспертное резюме, сухая аналитика.",
        "WEEKEND": "Тишина в эфире (отсутствие публикаций) или дайджест прессы."
    },
    IndustryArchetype.EXPERT_SERVICES: {
        "MON": "Разбор заблуждения: ключевые мифы в нише, с чем приходят клиенты.",
        "TUE": "Клинический/Рабочий случай: архитектура решения проблемы клиента.",
        "WED": "Пошаговый чеклист: как клиенту избежать ошибки на старте.",
        "THU": "Ответ на частый вопрос (FAQ): логическое снятие ключевого возражения.",
        "FRI": "Личный инсайт: суровый профессиональный опыт и выводы.",
        "WEEKEND": "Вдохновляющий профессиональный кейс, размышления о стандартах профессии."
    }
}


def get_available_formats(tier: SubscriptionTier) -> List[ContentFormat]:
    """
    Возвращает разрешенные форматы генерации на основе тарифа подписки.
    Предотвращает постановку тяжелых задач (каруселей/пазлов) от базовых пользователей.
    """
    tier_norm = SubscriptionTier.normalize(tier) if hasattr(SubscriptionTier, "normalize") else tier
    tier_limits = {
        SubscriptionTier.START: [
            ContentFormat.SINGLE_SHOT
        ],
        SubscriptionTier.BUSINESS: [
            ContentFormat.SINGLE_SHOT, 
            ContentFormat.CAROUSEL_LIGHT
        ],
        SubscriptionTier.CUSTOM: [
            ContentFormat.SINGLE_SHOT, 
            ContentFormat.CAROUSEL_LIGHT, 
            ContentFormat.CAROUSEL_HEAVY, 
            ContentFormat.CRYPTEX_PUZZLE
        ]
    }
    return tier_limits.get(tier_norm, [ContentFormat.SINGLE_SHOT])


# ==============================================================================
# 2. РЕЗОЛВЕР СЕМАНТИЧЕСКИХ КОНФЛИКТОВ (BILINGUAL VLM vs RAG)
# ==============================================================================

class SemanticConflictResolver:
    """
    Двуязычный (RU/EN) резолвер конфликтов между VLM-зрением и RAG-профилем бренда.
    Блокирует попадание бытовых дефектов и мусора в итоговый аналоговый промпт.
    """

    FORBIDDEN_VLM_CONTAMINANTS_BILINGUAL = {
        # Английские токены
        "plastic", "cheap", "cluttered", "trash", "dirty", "lowres", "messy", 
        "window sill", "radiator", "socket", "wire", "poor lighting", "blurry",
        # Русские токены (и стеммы)
        "пластик", "пластиковый", "дешевый", "дешево", "грязь", "грязный", "мусор",
        "подоконник", "батарея", "розетка", "провод", "кабель", "хлам", "бардак",
        "плохое освещение", "размытый", "шум", "кривой", "облезлый", "линолеум"
    }

    @classmethod
    def resolve_visual_anchors(cls, vlm_anchors: List[str], brand_props: List[str]) -> List[str]:
        cleaned_vlm = []
        for anchor in vlm_anchors:
            anchor_lower = anchor.lower().strip()
            if not anchor_lower:
                continue

            # Проверка на наличие стоп-слов из обоих языков
            is_contaminated = any(
                stop_word in anchor_lower 
                for stop_word in cls.FORBIDDEN_VLM_CONTAMINANTS_BILINGUAL
            )

            if not is_contaminated:
                cleaned_vlm.append(anchor)

        # Безусловный приоритет у RAG-якорей бренда (идут первыми в промпте)
        combined = list(dict.fromkeys(brand_props + cleaned_vlm[:3]))
        return combined


# ==============================================================================
# 3. ЭКСТРАКТОР КОММЕРЧЕСКИХ СУЩНОСТЕЙ ИЗ OCR
# ==============================================================================

class OCREntityExtractor:
    """
    Интеллектуальный экстрактор цен, позиций меню и ключевых офферов из сырого OCR.
    Отсекает юридический мусор (ИНН, адреса, реквизиты) и сохраняет только коммерческие факты.
    """

    NOISE_PATTERNS = [
        r'\b(?:инн|кпп|огрн|огрнип|бик|р/с|к/с|окпо)\b[:\s]*\d+',
        r'\b(?:ооо|зао|пао|ип|г\.|ул\.|д\.|стр\.|пом\.|тел|факс)\b[^\n]*',
        r'[-_—=]{3,}',                          # Разделительные линии
        r'^\s*\d+\s*$',                          # Одиночные номера страниц
    ]

    PRICE_PATTERNS = [
        r'([A-Za-zА-Яа-яЁё\s\-\"\'«»]{3,45})\s+[\.\-—–\s]*\s+(\d{2,6})\s*(?:руб|рублей|₽|k|\$|€)',
        r'(\d{2,6})\s*(?:руб|рублей|₽)\s*[-—–]\s*([A-Za-zА-Яа-яЁё\s\-\"\'«»]{3,45})'
    ]

    @classmethod
    def extract_compact_entities(cls, raw_ocr_text: Optional[str]) -> str:
        if not raw_ocr_text:
            return ""

        cleaned_text = raw_ocr_text
        for noise_pat in cls.NOISE_PATTERNS:
            cleaned_text = re.sub(noise_pat, '', cleaned_text, flags=re.IGNORECASE)

        extracted_items = []

        # 1. Поиск структурированных пар: Товар/Услуга + Цена
        for line in cleaned_text.split('\n'):
            line_str = line.strip()
            if not line_str or len(line_str) < 3:
                continue

            for price_pat in cls.PRICE_PATTERNS:
                matches = re.findall(price_pat, line_str, flags=re.IGNORECASE)
                for match in matches:
                    if isinstance(match, tuple):
                        item, price = match[0].strip(), match[1].strip()
                        if item.isdigit():
                            item, price = price, item
                        if len(item) > 2 and not item.isdigit():
                            extracted_items.append(f"{item}: {price}₽")

        # 2. Если регулярки не нашли явных пар (например, B2B скан договора без цен)
        if not extracted_items:
            meaningful_lines = [
                line.strip() for line in cleaned_text.split('\n')
                if len(line.strip()) > 10 and not any(w in line.lower() for w in ['страница', 'подпись', 'печать', 'договор'])
            ]
            extracted_items = meaningful_lines[:5]

        # Ограничиваем итоговую сводку 350 символами
        summary = " | ".join(dict.fromkeys(extracted_items[:8]))
        if len(summary) > 350:
            summary = summary[:350] + "..."

        return summary


# ==============================================================================
# 4. ШАБЛОНИЗАТОР ПРОМПТОВ (PROMPT ENGINE)
# ==============================================================================

class PromptEngine:
    """Шаблонизатор для сборки системного и пользовательского промпта LLM (Сайга/Llama-3)."""

    @classmethod
    def build_messages(
        cls,
        company_name: str,
        brand_props: List[str],
        rag_context: List[str],
        ocr_text: str,
        tov_instruction: str,
        industry: IndustryArchetype
    ) -> List[Dict[str, str]]:
        
        industry_role = "Senior B2B Copywriter" if industry == IndustryArchetype.B2B_CORPORATE else (
            "Senior Expert Consultant & Storyteller" if industry == IndustryArchetype.EXPERT_SERVICES else "Senior Lifestyle & Brand Copywriter"
        )

        system_prompt = f"""Ты — {industry_role}. Твоя задача — написать профессиональный пост для Telegram-канала компании "{company_name}".

ТВОИ ЖЕСТКИЕ ПРАВИЛА (СТРОГО):
1. Структура: Первая строка — цепляющий хук без приветствий. Далее главная мысль или раскрывающийся блок (используй символ > в начале цитаты). В конце — закрытый призыв к действию (CTA).
2. Tone of Voice на сегодня: {tov_instruction}
3. Запрещено: использовать спам-хэштеги, emoji больше 3 штук на весь пост, фейковые цифры, клише ("В этом динамично развивающемся мире").
4. Не здоровайся и не прощайся. Выдавай ТОЛЬКО готовый текст поста для Telegram.

БАЗА ЗНАНИЙ БРЕНДА (ФАКТЫ И УТП):
{" | ".join(rag_context) if rag_context else "Используй общую высокую экспертизу в нише."}
"""

        user_prompt = f"Напиши готовый пост для {company_name}."
        if ocr_text:
            user_prompt += f"\nОБЯЗАТЕЛЬНО включи в текст следующие коммерческие позиции и цены из меню/прайса/документа: {ocr_text}"

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]


# ==============================================================================
# 5. ОСНОВНОЙ ДВИЖОК СТРАТЕГИИ И ПЛАНИРОВАНИЯ
# ==============================================================================

class ContentStrategyEngine:
    """
    Движок генерации контент-плана и черновиков постов.
    """

    def __init__(self, dev_mode: bool = True):
        try:
            from core.llm_provider import SaigaLLMSkill
        except ImportError:
            try:
                from ai.core.llm_provider import SaigaLLMSkill
            except ImportError:
                SaigaLLMSkill = None

        if SaigaLLMSkill:
            self.llm_skill = SaigaLLMSkill(dev_mode=dev_mode)
        else:
            self.llm_skill = None

    def generate_strategy(
        self,
        company_name: str,
        niche: str,
        target_audience: str = "",
        key_usp: str = ""
    ) -> Dict[str, Any]:
        """
        Генерирует структурированную стратегию позиционирования, портрет покупателя (Persona)
        и арсенал триггеров/крючков (Viral Hooks & Funnel Matrix).
        """
        niche_lower = (niche or "").lower()
        
        # 1. Формирование портрета покупателя (Buyer Persona)
        if "кофе" in niche_lower or "еда" in niche_lower or "ресторан" in niche_lower:
            primary_pains = [
                "Невкусный или пережженный кофе в других местах",
                "Долгое ожидание в часы пик",
                "Неуютная атмосфера и отсутствие розеток/мест для работы",
                "Холодная или несвежая выпечка"
            ]
            buying_triggers = [
                "Аромат свежей обжарки и безупречный баланс вкуса",
                "Быстрая выдача за 90 секунд через предзаказ",
                "Эстетичный скандинавский интерьер и приветливые бариста",
                "Программа лояльности с кэшбэком"
            ]
        elif "красот" in niche_lower or "салон" in niche_lower or "барбер" in niche_lower:
            primary_pains = [
                "Непредсказуемый результат стрижки или ухода",
                "Нестерильные инструменты и сомнительная косметика",
                "Навязывание лишних дорогостоящих процедур"
            ]
            buying_triggers = [
                "Портфолио реальных работ и дипломы мастеров",
                "100% стерилизация в крафт-пакетах при клиенте",
                "Премиальные сертифицированные эко-составы"
            ]
        elif "it" in niche_lower or "b2b" in niche_lower or "софт" in niche_lower:
            primary_pains = [
                "Срыв сроков и раздувание сметы подрядчиками",
                "Сложность поддержки чужого легаси-кода",
                "Отсутствие прозрачной аналитики и SLA"
            ]
            buying_triggers = [
                "Фиксация KPI и штрафов за срыв сроков в договоре",
                "Сквозная демонстрация архитектуры и CI/CD",
                "Подтвержденный ROI и измеримые кейсы"
            ]
        else:
            primary_pains = [
                f"Некачественное оказание услуг в сфере {niche}",
                "Непрозрачное ценообразование и скрытые комиссии",
                "Сложность получения квалифицированной консультации"
            ]
            buying_triggers = [
                f"Гарантия результата от бренда {company_name}",
                "Открытые отзывы и репутация на рынке",
                "Персональный менеджер и поддержка 24/7"
            ]

        buyer_persona = {
            "target_audience": target_audience or f"Клиенты, ценящие качество и надежность в нише {niche}",
            "primary_pains": primary_pains,
            "buying_triggers": buying_triggers,
            "decision_making_speed": "Средняя (1-3 дня)",
            "preferred_channels": ["Telegram", "VK", "Геосервисы"]
        }

        funnel_matrix = {
            "top_of_funnel": ["Отраслевые тренды", "Разрушение мифов", "Эстетичные UGC-кадры"],
            "middle_of_funnel": ["Кейсы и до/после", "Разбор сложных задач", "Отзывы клиентов"],
            "bottom_of_funnel": ["Спецпредложения", "Лимитированные комбо", "Прямой призыв к заказу"]
        }

        hooks_arsenal = [
            f"Почему 80% клиентов выбирают {company_name} вместо типовых решений?",
            f"3 фатальные ошибки при выборе услуг в сфере {niche}",
            f"Как получить максимальный результат уже в первый день сотрудничества"
        ]

        return {
            "company_name": company_name,
            "niche": niche,
            "buyer_persona": buyer_persona,
            "funnel_matrix": funnel_matrix,
            "hooks_arsenal": hooks_arsenal
        }

    def _get_day_key(self, target_date: datetime) -> str:
        weekday = target_date.weekday()
        if weekday == 0:
            return "MON"
        elif weekday == 1:
            return "TUE"
        elif weekday == 2:
            return "WED"
        elif weekday == 3:
            return "THU"
        elif weekday == 4:
            return "FRI"
        else:
            return "WEEKEND"

    def _compose_image_specs(
        self,
        brand: BrandProfile,
        raw_input: RawDataIngestion,
        format_type: ContentFormat
    ) -> List[ImageGenerationSpec]:
        """
        Составляет список спецификаций генерации изображений с разрешением конфликтов.
        """
        resolved_anchors = SemanticConflictResolver.resolve_visual_anchors(
            vlm_anchors=raw_input.vlm_visual_anchors,
            brand_props=brand.brand_props
        )
        anchors_str = ", ".join(resolved_anchors) if resolved_anchors else "natural authentic materials"

        base_analog_formula = (
            "Shot on Hasselblad H6D-100c, 85mm prime lens f/2.8, camera angled downwards at 35 degrees tilt, "
            "authentic 35mm RAW color photo with natural fine organic film grain Kodak Portra 400 ISO 400:1.15, "
            "soft directional morning window daylight 5600K, hyper-realistic physical materials, zero CGI"
        )

        specs: List[ImageGenerationSpec] = []

        if format_type == ContentFormat.SINGLE_SHOT:
            prompt = (
                f"Commercial hero shot for {brand.company_name}. "
                f"Featuring {anchors_str}. "
                f"{base_analog_formula}."
            )
            specs.append(ImageGenerationSpec(
                prompt=prompt,
                aspect_ratio="1:1",
                width=1024,
                height=1024
            ))

        elif format_type == ContentFormat.CAROUSEL_LIGHT:
            # 3 слайда: Окружение -> Макро деталь -> В действии
            angles = [
                ("Hero establishing view", "1:1", 1024, 1024),
                ("Sensory extreme close-up macro texture", "1:1", 1024, 1024),
                ("Human interaction and use context", "1:1", 1024, 1024)
            ]
            for angle_name, aspect, w, h in angles:
                p = f"{angle_name} of {brand.company_name} presentation. Featuring {anchors_str}. {base_analog_formula}."
                specs.append(ImageGenerationSpec(prompt=p, aspect_ratio=aspect, width=w, height=h))

        elif format_type == ContentFormat.CRYPTEX_PUZZLE:
            # 4 слайда под нарезку Y = 0-22%, 22-44%, 44-76%, 76-100%
            for i in range(4):
                p = (
                    f"Seamless vertical slice layer {i+1} presentation for {brand.company_name}. "
                    f"Featuring {anchors_str}. {base_analog_formula}."
                )
                specs.append(ImageGenerationSpec(
                    prompt=p,
                    aspect_ratio="4:5",
                    width=1080,
                    height=1350
                ))

        else:
            # Fallback
            specs.append(ImageGenerationSpec(
                prompt=f"Commercial photo for {brand.company_name}. {anchors_str}. {base_analog_formula}.",
                aspect_ratio="1:1",
                width=1024,
                height=1024
            ))

        return specs

    def _llm_generate_text(
        self,
        brand: BrandProfile,
        raw_input: RawDataIngestion,
        tov_instruction: str,
        format_type: ContentFormat
    ) -> str:
        """
        Вызов локальной LLM Сайга (через PromptEngine и SaigaLLMSkill) для синтеза текста.
        0 GPU cost — только текстовый инференс.
        """
        compact_ocr = OCREntityExtractor.extract_compact_entities(raw_input.ocr_raw_text)
        
        messages = PromptEngine.build_messages(
            company_name=brand.company_name,
            brand_props=brand.brand_props,
            rag_context=raw_input.rag_context_snippets,
            ocr_text=compact_ocr,
            tov_instruction=tov_instruction,
            industry=brand.industry
        )

        if self.llm_skill:
            try:
                return self.llm_skill.generate_chat(messages=messages, max_tokens=600)
            except Exception as e:
                logger.error(f"⚠️ Сбой вызова SaigaLLMSkill: {e}")

        # Детерминированный Fallback каркас
        ocr_context_str = f" [Позиции меню/документа: {compact_ocr}]" if compact_ocr else ""
        rag_facts_str = f" [УТП: {', '.join(raw_input.rag_context_snippets[:2])}]" if raw_input.rag_context_snippets else ""

        if brand.industry == IndustryArchetype.B2B_CORPORATE:
            hook = f"📊 Анализ и стандарты: как {brand.company_name} обеспечивает надежность процессов"
            body = (
                f"В корпоративном сегменте ключевое значение имеет прозрачность и минимизация рисков.\n"
                f"> {tov_instruction}{ocr_context_str}{rag_facts_str}\n"
                f"Мы внедряем строгий аудит на каждом этапе сотрудничества."
            )
            cta = "📩 Ознакомьтесь с подробным регламентом по ссылке в профиле или запросите аудит в директ."
        elif brand.industry == IndustryArchetype.EXPERT_SERVICES:
            hook = f"💡 Разбор практики: ключевые нюансы в работе {brand.company_name}"
            body = (
                f"Частая ошибка клиентов — попытка решить сложную задачу типовыми методами.\n"
                f"> {tov_instruction}{ocr_context_str}\n"
                f"Пошаговый алгоритм позволяет сэкономить ресурсы и гарантировать результат."
            )
            cta = "📌 Сохраните этот чек-лист в закладки или запишитесь на персональный разбор."
        else:
            hook = f"☕ Атмосфера и детали: утро вместе с {brand.company_name}"
            body = (
                f"Каждая деталь имеет значение, когда речь идет о настоящем вкусе и тактильном комфорте.\n"
                f"> {tov_instruction}{ocr_context_str}\n"
                f"Создаем моменты, к которым хочется возвращаться каждый день."
            )
            cta = "👉 Выберите свой любимый вариант по ссылке в описании профиля."

        return f"{hook}\n\n{body}\n\n{cta}"

    def generate_post_draft(
        self,
        brand: BrandProfile,
        raw_input: RawDataIngestion,
        target_date: datetime,
        forced_format: Optional[ContentFormat] = None
    ) -> PostDraft:
        """
        Основной метод создания черновика поста (DRAFT_TEXT).
        Выполняется за миллисекунды, расходует 0 GPU-ресурсов.
        """
        # 1. Проверка доступных форматов по тарифу подписки
        allowed_formats = get_available_formats(brand.tier)
        selected_format = forced_format if (forced_format in allowed_formats) else allowed_formats[0]

        # 2. Определение ToV дня по матрице драматургии
        day_key = self._get_day_key(target_date)
        day_tov_instruction = DRAMATURGY_MATRIX[brand.industry].get(day_key, "Качественный экспертный пост")

        # 3. Синтез текста (0 GPU, LLM инференс)
        text_content = self._llm_generate_text(
            brand=brand,
            raw_input=raw_input,
            tov_instruction=day_tov_instruction,
            format_type=selected_format
        )

        # 4. Формирование спецификаций изображений с фильтром конфликтов
        image_specs = self._compose_image_specs(
            brand=brand,
            raw_input=raw_input,
            format_type=selected_format
        )

        # 5. Сборка PostDraft
        post = PostDraft(
            post_id=str(uuid.uuid4()),
            brand_id=brand.brand_id,
            target_date=target_date,
            format=selected_format,
            status=PostLifecycleStatus.DRAFT_TEXT,
            text_content=text_content,
            image_specs=image_specs,
            rendered_image_urls=[]
        )

        # 6. Расчет предварительной стоимости VRAM
        post.vram_cost_mb = VRAMCostCalculator.calculate_total_post_vram(post, dev_simulation_mode=True)
        return post

    def generate_content_plan(
        self,
        company_name: str,
        niche: str,
        visual_grid_dna: Optional[Dict[str, Any]] = None,
        rag_insights: Optional[Dict[str, Any]] = None,
        days_count: int = 7,
        country: Optional[str] = None,
        city: Optional[str] = None,
        start_date: Optional[str] = None,
        feedback_insights: Optional[Dict[str, Any]] = None,
        user_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Генерирует контент-план на N дней, привязанный к болям аудитории из RAG
        и сопоставленный со слотами матрицы 3x3 визуальной сетки ленты.
        """
        grid_slots = (visual_grid_dna or {}).get("grid_3x3_slots", [])
        brand_colors = (visual_grid_dna or {}).get("brand_hex_palette", ["#1F2937", "#3B82F6", "#F3F4F6"])
        pains = (rag_insights or {}).get("pain_points", [
            "Страх некачественного результата",
            "Высокие цены и скрытые переплаты",
            "Нехватка времени и сложный процесс"
        ])

        stages = ["TOFU", "MOFU", "BOFU", "TOFU", "MOFU", "BOFU", "MOFU"]
        plan_items = []

        for day in range(1, days_count + 1):
            stage = stages[(day - 1) % len(stages)]
            slot_idx = (day - 1) % (len(grid_slots) if grid_slots else 9)
            slot_info = grid_slots[slot_idx] if grid_slots and slot_idx < len(grid_slots) else {
                "slot": slot_idx + 1,
                "type": "lifestyle",
                "title": "Брендовый кадр",
                "description": "Эстетичный кадр с фирменными цветами"
            }
            pain = pains[(day - 1) % len(pains)]

            if stage == "TOFU":
                topic = f"Как избежать главной ошибки в {niche}: секреты профессионалов"
                format_type = "Пост-разбор + Вопрос в комментариях"
            elif stage == "MOFU":
                topic = f"Честно о том, как мы закрываем проблему «{pain}» в {company_name}"
                format_type = "Кейс До/После + Демонстрация процесса"
            else: # BOFU
                topic = f"Специальное предложение от «{company_name}»: гарантия качества и выгода"
                format_type = "Продающий оффер + Промокод + CTA"

            plan_items.append({
                "day": day,
                "stage": stage,
                "topic": topic,
                "target_pain_point": pain,
                "format": format_type,
                "grid_slot": {
                    "slot_number": slot_info.get("slot", slot_idx + 1),
                    "shot_type": slot_info.get("type"),
                    "visual_title": slot_info.get("title"),
                    "visual_guidance": f"Съемка в стиле '{slot_info.get('title')}'. Палитра: {', '.join(brand_colors[:2])}."
                }
            })

        return {
            "status": "success",
            "company_name": company_name,
            "niche": niche,
            "plan_days": plan_items,
            "brand_palette": brand_colors,
            "summary": f"Контент-план на {days_count} дней успешно сбалансирован по воронке TOFU/MOFU/BOFU и синхронизирован с 3x3 сеткой."
        }

    def generate_30day_content_plan(
        self,
        company_name: str,
        niche: str,
        city: Optional[str] = "Москва",
        country: Optional[str] = "Россия",
        rag_insights: Optional[Dict[str, Any]] = None,
        user_data: Optional[Dict[str, Any]] = None,
        visual_grid_dna: Optional[Dict[str, Any]] = None,
        feedback_insights: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Алиас для генерации 30-дневного (или N-дневного) контент-плана."""
        days = 30
        if user_data and user_data.get("days_count"):
            days = int(user_data["days_count"])
        return self.generate_content_plan(
            company_name=company_name,
            niche=niche,
            visual_grid_dna=visual_grid_dna,
            rag_insights=rag_insights,
            days_count=days,
            country=country,
            city=city,
            feedback_insights=feedback_insights,
            user_data=user_data,
        )



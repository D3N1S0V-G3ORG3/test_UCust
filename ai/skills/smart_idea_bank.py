"""
File: ai/skills/smart_idea_bank.py
Smart Idea Bank & Dynamic Placeholder Engine for UCust AI.

Архитектурный принцип:
- Календарь автоматической воронки продаж (Funnel Schedule) работает автономно и строго соблюдает конверсионную логику (TOFU -> MOFU -> BOFU).
- Плейсхолдеры и «Банк быстрых идей» (Idea Bank) отделены интерфейсно и служат источником ситуативных тем.
- При выборе идеи система анализирует воронку через ContextRouter и выдает рекомендацию по размещению (в черновики, внеплановый пост или конкретный этап воронки) без разрушения конверсионной архитектуры.
"""

from __future__ import annotations

import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from collectors.event_holiday_collector import EventHolidayCollector
from skills.context_router import (
    ContextRouterSkill, RoutingDirective, QuadrantEnum, FunnelLockEnum, IntentModeEnum
)

logger = logging.getLogger("smart_idea_bank")


class QuickIdeaCard(BaseModel):
    id: str
    title: str
    description: str
    date_str: str
    days_until: int
    category: str = Field("holiday", description="holiday | seasonal | trend | evergreen")
    suggested_funnel: str = Field("TOFU_UNAWARE", description="TOFU_UNAWARE | MOFU_PROBLEM | BOFU_SOLUTION")
    suggested_framework: str = Field("PAS", description="PAS | AIDA | BAB")
    niche_relevance: float = Field(0.85, description="0.0 - 1.0 relevance score")
    crossover_angle: Optional[str] = None
    sample_hook: str = ""


class DynamicPlaceholder(BaseModel):
    placeholder_text: str
    suggested_topic: str
    source_type: str = Field("calendar", description="calendar | seasonal | evergreen | trend")
    funnel_stage: str = "TOFU"
    hint: str = "Нажмите Tab для автозаполнения"


class FunnelPlacementVerdict(BaseModel):
    is_funnel_safe: bool
    placement_status: str = Field("safe", description="safe | warning | conflict")
    detected_funnel_stage: str
    recommended_target: str = Field("draft", description="draft | tofu_slot | mofu_slot | bofu_slot | unscheduled_story")
    marketing_framework: str
    cta_guidance: str
    explanation: str
    alternative_slots: List[str] = Field(default_factory=list)


class SmartIdeaBank:
    """
    Интеллектуальный банк идей и генератор динамических плейсхолдеров.
    Связывает ситуативный контент с воронками продаж без риска поломки календаря.
    """

    def __init__(self):
        self.holiday_collector = EventHolidayCollector()
        self.router = ContextRouterSkill()

    def get_upcoming_events(
        self,
        niche: str = "Общий бизнес",
        country: str = "россия",
        city: str = "Москва",
        days_ahead: int = 21,
        start_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Извлекает предстоящие праздники и инфоповоды на ближайшие N дней.
        """
        now = start_date or datetime.now(timezone.utc)
        if now.tzinfo is not None:
            now_naive = now.replace(tzinfo=None)
        else:
            now_naive = now

        events = self.holiday_collector.get_calendar_events(
            country=country,
            city=city,
            niche=niche,
            start_date=now_naive,
            days_count=days_ahead
        )
        for e in events:
            e["days_until"] = e.get("day_number", 1) - 1
            e["is_professional"] = e.get("type") == "niche_professional_holiday"
        return events

    def get_dynamic_placeholders(
        self,
        niche: str = "Бизнес",
        company_name: str = "",
        current_date: Optional[datetime] = None,
        limit: int = 5
    ) -> List[DynamicPlaceholder]:
        """
        Генерирует умные контекстные подсказки для плейсхолдера поля ввода темы.
        Позволяет пользователю мгновенно вдохновиться или вставить тему по Tab.
        """
        events = self.get_upcoming_events(niche=niche, days_ahead=21, start_date=current_date)
        placeholders: List[DynamicPlaceholder] = []

        comp = company_name or "наш бренд"

        # 1. Плейсхолдеры на основе ближайших инфоповодов
        for evt in events[:3]:
            title = evt.get("title", "")
            days = evt.get("days_until", 0)
            day_text = "сегодня" if days == 0 else f"через {days} дн." if days > 1 else "завтра"

            sample_topic = f"{title}: как {comp} встречает праздник и что приготовил для клиентов"
            text = f"💡 Идея ({day_text}): {title} — как это связано с вашими клиентами?"
            
            # Оцениваем воронку
            routing = self.router.route_task(topic=sample_topic, company_name=comp, niche=niche)
            funnel_code = "TOFU" if "TOFU" in routing.text_directive.funnel_lock.value else "MOFU"

            placeholders.append(
                DynamicPlaceholder(
                    placeholder_text=text,
                    suggested_topic=sample_topic,
                    source_type="calendar",
                    funnel_stage=funnel_code,
                    hint="Нажмите Tab, чтобы вставить тему праздника"
                )
            )

        # 2. Отраслевые ситуативные и сезонные плейсхолдеры
        niche_lower = niche.lower()
        if any(k in niche_lower for k in ["кофе", "кафе", "ресторан", "food"]):
            placeholders.append(
                DynamicPlaceholder(
                    placeholder_text="💡 Идея: Секрет идеального помола для утреннего бодрящего фильтра",
                    suggested_topic="Разбор: почему свежая обжарка и правильный помол меняют вкус кофе",
                    source_type="seasonal",
                    funnel_stage="MOFU",
                    hint="Нажмите Tab для экспертной темы"
                )
            )
            placeholders.append(
                DynamicPlaceholder(
                    placeholder_text="💡 Идея: Что заказать в пятничный вечер — топ авторских напитков недели",
                    suggested_topic="Пятничный гид по авторскому меню: напитки недели со скидкой",
                    source_type="evergreen",
                    funnel_stage="BOFU",
                    hint="Нажмите Tab для коммерческого оффера"
                )
            )
        elif any(k in niche_lower for k in ["it", "разработ", "софт", "saas", "ai"]):
            placeholders.append(
                DynamicPlaceholder(
                    placeholder_text="💡 Идея: 3 скрытые ошибки в CI/CD пайплайне, сжигающие бюджет команды",
                    suggested_topic="Разбор кейса: как оптимизация тестов сократила время деплоя на 60%",
                    source_type="evergreen",
                    funnel_stage="MOFU",
                    hint="Нажмите Tab для B2B разбора"
                )
            )
            placeholders.append(
                DynamicPlaceholder(
                    placeholder_text="💡 Идея: Как ИИ-агенты заменяют рутинные операции в поддержке 24/7",
                    suggested_topic="Внедрение AI-ассистентов: ускорение обработки заявок в 4 раза",
                    source_type="evergreen",
                    funnel_stage="BOFU",
                    hint="Нажмите Tab для оффера"
                )
            )
        else:
            placeholders.append(
                DynamicPlaceholder(
                    placeholder_text=f"💡 Идея: Главный миф о сфере «{niche}», в который все еще верят",
                    suggested_topic=f"Развенчиваем популярный стереотип в нише {niche}: реальный опыт {comp}",
                    source_type="evergreen",
                    funnel_stage="TOFU",
                    hint="Нажмите Tab для вовлекающего поста"
                )
            )
            placeholders.append(
                DynamicPlaceholder(
                    placeholder_text=f"💡 Идея: Как выбрать надежного партнера в {niche} и не переплатить",
                    suggested_topic=f"Чек-лист проверки поставщика услуг в {niche} перед заключением договора",
                    source_type="evergreen",
                    funnel_stage="MOFU",
                    hint="Нажмите Tab для экспертного чек-листа"
                )
            )

        return placeholders[:limit]

    def get_quick_ideas_bank(
        self,
        niche: str = "Бизнес",
        country: str = "россия",
        days_ahead: int = 21,
        company_name: str = ""
    ) -> List[QuickIdeaCard]:
        """
        Формирует структурированный банк идей (Idea Bank), сгруппированный и оцененный
        с точки зрения релевантности и этапа воронки продаж.
        """
        events = self.get_upcoming_events(niche=niche, country=country, days_ahead=days_ahead)
        comp = company_name or "Бренд"
        cards: List[QuickIdeaCard] = []

        for idx, evt in enumerate(events):
            title = evt.get("title", "")
            date_str = evt.get("date", "")
            days_until = evt.get("days_until", 0)
            vibe = evt.get("vibe", "")
            is_prof = evt.get("is_professional", False)

            # Определяем драматургию и угол кроссовера
            routing = self.router.route_task(
                topic=f"{title} {vibe}",
                company_name=comp,
                niche=niche
            )

            funnel_stage = routing.text_directive.funnel_lock.value
            framework = routing.text_directive.forced_framework
            
            crossover = (
                f"Мост через ценности бренда и уютную атмосферу ({routing.visual_anchor.crossover_props})"
                if routing.intent_mode == IntentModeEnum.LIFESTYLE_CROSSOVER
                else "Прямой отраслевой инфоповод для повышения авторитета"
            )

            sample_hook = (
                f"Через {days_until} дн. — {title}. Отличный повод поделиться закулисьем {comp}."
                if days_until > 0 else
                f"Сегодня отмечается {title}! Как команда {comp} встречает этот день."
            )

            cards.append(
                QuickIdeaCard(
                    id=f"idea_{idx}_{days_until}",
                    title=title,
                    description=vibe,
                    date_str=date_str,
                    days_until=days_until,
                    category="holiday" if not is_prof else "professional",
                    suggested_funnel=funnel_stage,
                    suggested_framework=framework,
                    niche_relevance=0.95 if is_prof else 0.75,
                    crossover_angle=crossover,
                    sample_hook=sample_hook
                )
            )

        return cards

    def suggest_top_ideas(
        self,
        niche: str = "Бизнес",
        limit: int = 5,
        company_name: str = "",
        country: str = "россия",
        days_ahead: int = 21,
        **kwargs: Any
    ) -> List[Dict[str, Any]]:
        """
        Предлагает структурированный банк лучших идей для контента (Idea Bank) для заданной ниши и бренда.
        Объединяет календарные инфоповоды, отраслевые праздники, ситуативные темы и вечнозеленые рубрики.
        """
        cards = self.get_quick_ideas_bank(
            niche=niche,
            country=country,
            days_ahead=days_ahead,
            company_name=company_name
        )
        ideas: List[Dict[str, Any]] = [c.dict() for c in cards]

        # Если календарных идей меньше заданного лимита, дополняем вечнозелеными плейсхолдерами
        if len(ideas) < limit:
            placeholders = self.get_dynamic_placeholders(
                niche=niche,
                company_name=company_name,
                limit=max(limit - len(ideas), 3)
            )
            for idx, p in enumerate(placeholders):
                ideas.append({
                    "id": f"idea_evergreen_{idx}",
                    "title": p.suggested_topic,
                    "description": p.placeholder_text,
                    "date_str": "Регулярная рубрика",
                    "days_until": 0,
                    "category": p.source_type,
                    "suggested_funnel": p.funnel_stage,
                    "suggested_framework": "AIDA",
                    "niche_relevance": 0.90,
                    "crossover_angle": p.hint,
                    "sample_hook": p.suggested_topic,
                })

        return ideas[:limit]

    def evaluate_funnel_placement(
        self,
        topic: str,
        niche: str = "Бизнес",
        company_name: str = "UCust",
        target_slot_date: Optional[str] = None,
        target_slot_type: Optional[str] = None,
        is_override_scheduled_slot: bool = False
    ) -> FunnelPlacementVerdict:
        """
        Архитектурный советник по размещению идеи в воронку:
        - Анализирует семантику темы через ContextRouter.
        - Сопоставляет тип идеи (вирусный мем, экспертный разбор, жесткий оффер) с целевым слотом.
        - Защищает активные BOFU-слоты от случайного затирания вирусными темами.
        """
        routing: RoutingDirective = self.router.route_task(
            topic=topic,
            company_name=company_name,
            niche=niche
        )

        detected_funnel = routing.text_directive.funnel_lock.value
        framework = routing.text_directive.forced_framework
        is_lifestyle_crossover = routing.intent_mode == IntentModeEnum.LIFESTYLE_CROSSOVER

        topic_lower = topic.lower()
        is_direct_offer = any(w in topic_lower for w in ["скидк", "акци", "по цене", "спецпредложен", "купить", "заказать", "только до", "оффер", "промокод"])
        if is_direct_offer:
            detected_funnel = "BOFU_DECISION"
            framework = "AIDA"

        # 1. Если пользователь пытается перезаписать существующий конверсионный слот (например, пятничный BOFU)
        if is_override_scheduled_slot and target_slot_type:
            target_type_upper = target_slot_type.upper()
            
            # Конфликт: затирание BOFU оффера легким мемом или праздником
            if "BOFU" in target_type_upper and ("TOFU" in detected_funnel or is_lifestyle_crossover):
                return FunnelPlacementVerdict(
                    is_funnel_safe=False,
                    placement_status="warning",
                    detected_funnel_stage=detected_funnel,
                    recommended_target="draft",
                    marketing_framework=framework,
                    cta_guidance="Мягкое вовлечение / Реакции (Без прямого жесткого CTA на покупку)",
                    explanation=(
                        f"⚠️ Внимание: Выбранный слот в календаре предназначен для конверсии и продаж ({target_slot_type}), "
                        f"а тема «{topic}» является вирусной/охватной (TOFU). "
                        f"Прямая замена разрушит прогрев аудитории. Рекомендуем сохранить идею в черновики "
                        f"или опубликовать как внеплановый сторис/пост выходного дня."
                    ),
                    alternative_slots=["draft", "unscheduled_story", "weekend_lifestyle_slot"]
                )

        # 2. Рекомендация безопасного назначения
        if "TOFU" in detected_funnel or is_lifestyle_crossover:
            recommended_target = "tofu_slot"
            explanation = (
                f"Тема «{topic}» идеально подходит для этапа вовлечения и охвата (TOFU). "
                f"Рекомендуется поставить в начало контент-цикла (Пн-Вт) или опубликовать в черновики."
            )
            cta_guidance = "Вовлекающий вопрос в конце поста, опрос или реакция."
        elif "MOFU" in detected_funnel:
            recommended_target = "mofu_slot"
            explanation = (
                f"Тема «{topic}» несет экспертную ценность и снимает возражения (MOFU). "
                f"Рекомендуется назначить на середину недели (Ср-Чт) в связку с разбором решений."
            )
            cta_guidance = "Призыв сохранить пост, перейти к подробному чек-листу или задать вопрос в комментариях."
        else:
            recommended_target = "bofu_slot"
            explanation = (
                f"Тема «{topic}» направлена на принятие решения и покупку (BOFU). "
                f"Идеально ложится в слот пятничного спецпредложения или прямого оффера."
            )
            cta_guidance = "Четкий призыв к действию (The One Thing): ссылка на оформление, ЛС или запись."

        return FunnelPlacementVerdict(
            is_funnel_safe=True,
            placement_status="safe",
            detected_funnel_stage=detected_funnel,
            recommended_target=recommended_target,
            marketing_framework=framework,
            cta_guidance=cta_guidance,
            explanation=explanation,
            alternative_slots=["draft", recommended_target]
        )

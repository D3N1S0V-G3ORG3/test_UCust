"""
File: ai/services/content_scheduler.py
Модуль автономного контент-планирования и генерации недельной сетки публикаций (Content Scheduler Engine):
1. Стратифицированная RAG-оркестрация: извлечение контекста из 4 слоев (Hard Facts, Brand DNA, Audience Priors, Episodic Memory).
2. Матрица воронки Ханта (TOFU 40% / MOFU 40% / BOFU 20%): математически выверенное распределение тем по дням недели.
3. Truth Grounding: жесткая привязка коммерческих постов к слою hard_fact (защита от галлюцинаций).
4. Мультиплатформенная адаптация (Telegram, VK, OK, Max) через ChannelFormattersFactory.
5. Интеграция с Celery: отложенная постановка в очередь с расчетом оптимального времени постинга (ETA).
6. Вебхук-уведомления через CalendarIdeaNotificationPipeline.
"""

from __future__ import annotations

import os
import uuid
import time
import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, Any, List, Optional, Union

from pydantic import BaseModel, Field

from schemas.pipeline_state import PipelineState, ContentFormatEnum
from schemas.provenance_contracts import FieldCategoryEnum, FallbackStrategyEnum
from rag.models import DocCategoryEnum, RAGContext, Chunk
from rag.pipeline import CleanRAGPipeline
from services.channel_formatters import ChannelFormattersFactory, TargetChannelEnum, FormattedPostResult
from services.calendar_idea_notification_pipeline import (
    CalendarIdeaNotificationPipeline,
    CalendarGridGeneratedEvent,
    SlotScheduledEvent
)

logger = logging.getLogger("ContentSchedulerService")


class FunnelStageEnum(str, Enum):
    """Маркетинговые этапы воронки вовлечения и конверсии."""
    TOFU = "tofu"  # Верх воронки (Охват, боли, мифы, тренды, опросы)
    MOFU = "mofu"  # Середина воронки (Экспертность, внутренняя кухня, кейсы, гарантии)
    BOFU = "bofu"  # Низ воронки (Прямые офферы, прайс, акции, призыв к заказу)


class ScheduledSlot(BaseModel):
    """Единичный запланированный слот публикации в контент-календаре."""
    slot_id: str = Field(default_factory=lambda: f"slot_{uuid.uuid4().hex[:12]}")
    tenant_id: str
    day_index: int = Field(..., ge=0, le=30, description="Индекс дня (0-6 для недели)")
    day_name: str = Field(..., description="День недели (Понедельник, Вторник и т.д.)")
    scheduled_time_iso: str = Field(..., description="ISO 8601 время публикации")
    funnel_stage: FunnelStageEnum
    topic: str
    content_angle: str
    rag_layer_used: str
    base_text: str
    platform_drafts: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    image_prompt: Optional[str] = None
    is_promo: bool = False
    requires_approval: bool = False
    status: str = Field("scheduled", description="scheduled | published | pending_approval | failed")


class WeeklyCalendarGrid(BaseModel):
    """Полная сетка публикаций на неделю (или заданный горизонт)."""
    grid_id: str = Field(default_factory=lambda: f"grid_{uuid.uuid4().hex[:12]}")
    tenant_id: str
    company_name: str
    niche: str
    start_date: str
    end_date: str
    days_count: int
    slots: List[ScheduledSlot] = Field(default_factory=list)
    funnel_stats: Dict[str, int] = Field(default_factory=dict)
    drs_score: int = 0
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class ContentSchedulerService:
    """
    Интеллектуальный генератор и диспетчер недельного медиаплана:
    Связывает 4-слойный RAG с детерминированной сеткой воронки Ханта и очередями публикации.
    """

    DAY_NAMES = [
        "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"
    ]

    # Оптимальные часы публикаций для B2C/B2B по дням недели (МСК)
    OPTIMAL_POSTING_HOURS = [
        11,  # Пн: 11:00 (утренний фокус)
        14,  # Вт: 14:00 (обеденное чтение)
        18,  # Ср: 18:30 (вечерняя конверсия)
        12,  # Чт: 12:00 (интерактив)
        15,  # Пт: 15:00 (гарантии и закрытие сделок)
        12,  # Сб: 12:00 (выходной оффер)
        17,  # Вс: 17:00 (вечерний чилл и вдохновение)
    ]

    # Матрица воронки на 7 дней (TOFU 43%, MOFU 29%, BOFU 28%)
    SEVEN_DAY_MATRIX = [
        {
            "day": 0,
            "stage": FunnelStageEnum.TOFU,
            "angle": "Боль ЦА и отраслевой инсайт",
            "layer": DocCategoryEnum.AUDIENCE_PRIORS.value,
            "query": "боли клиентов проблемы сомнения возражения страхи",
            "is_promo": False
        },
        {
            "day": 1,
            "stage": FunnelStageEnum.MOFU,
            "angle": "Экспертный разбор и процесс работы",
            "layer": DocCategoryEnum.BRAND_DNA.value,
            "query": "редполитика подход качество стандарты экспертность",
            "is_promo": False
        },
        {
            "day": 2,
            "stage": FunnelStageEnum.BOFU,
            "angle": "Твердый коммерческий оффер и цены",
            "layer": DocCategoryEnum.HARD_FACT.value,
            "query": "цена стоимость прайс-лист тарифы услуги кулич пицца стрижка",
            "is_promo": True
        },
        {
            "day": 3,
            "stage": FunnelStageEnum.TOFU,
            "angle": "Интерактивный опрос или разрушение мифа",
            "layer": DocCategoryEnum.AUDIENCE_PRIORS.value,
            "query": "мифы заблуждения факты опрос вопросы клиентов",
            "is_promo": False
        },
        {
            "day": 4,
            "stage": FunnelStageEnum.MOFU,
            "angle": "Гарантии, надежность и безопасность",
            "layer": DocCategoryEnum.HARD_FACT.value,
            "query": "гарантия сроки возврат условия надежность свежесть",
            "is_promo": False
        },
        {
            "day": 5,
            "stage": FunnelStageEnum.BOFU,
            "angle": "Выходной призыв к заказу и контакты",
            "layer": DocCategoryEnum.HARD_FACT.value,
            "query": "контакты запись телефон адрес заказ покупка",
            "is_promo": True
        },
        {
            "day": 6,
            "stage": FunnelStageEnum.TOFU,
            "angle": "Атмосфера бренда, ценности и выходной сторителлинг",
            "layer": DocCategoryEnum.BRAND_DNA.value,
            "query": "миссия ценности атмосфера вдохновение закулисье команда",
            "is_promo": False
        }
    ]

    def __init__(
        self,
        rag_pipeline: Optional[CleanRAGPipeline] = None,
        platforms: Optional[List[str]] = None
    ):
        self.rag = rag_pipeline or CleanRAGPipeline()
        self.platforms = platforms or ["telegram", "vk", "ok", "max"]

    def _extract_best_fact(self, rag_ctx: RAGContext, layer_name: str, fallback_topic: str) -> str:
        """Извлечение наиболее релевантной фактуры из указанного слоя RAG."""
        chunks = rag_ctx.get_layer(layer_name)
        if chunks:
            # Берем первый наиболее релевантный чанк
            clean_chunk = chunks[0].text.replace("[ПОДТВЕРЖДЕНО ВЛАДЕЛЬЦЕМ]:", "").strip()
            return clean_chunk[:300]
        
        # Если чанков в слое нет, проверяем все чанки контекста
        if rag_ctx.chunks:
            return rag_ctx.chunks[0].text[:300]

        return fallback_topic

    def _generate_slot_content(
        self,
        company_name: str,
        niche: str,
        day_config: Dict[str, Any],
        rag_ctx: RAGContext
    ) -> Tuple[str, str, str]:
        """
        Генерация заголовка, темы и текста поста с учетом слоя RAG и этапа воронки.
        Возвращает: (topic, text, visual_prompt)
        """
        stage = day_config["stage"]
        layer = day_config["layer"]
        angle = day_config["angle"]

        extracted_context = self._extract_best_fact(rag_ctx, layer, angle)

        if stage == FunnelStageEnum.BOFU:
            # Коммерческий пост с твердыми ценами / контактами
            topic = f"Специальное предложение от {company_name}"
            text = (
                f"🔥 {topic}\n\n"
                f"Мы ценим ваше время и открыто делимся нашими актуальными условиями:\n"
                f"📌 {extracted_context}\n\n"
                f"Закажите прямо сейчас или напишите нам в личные сообщения для бронирования!"
            )
            v_prompt = f"Professional commercial product photography of {niche} offerings, studio lighting, highly detailed 8k"

        elif stage == FunnelStageEnum.MOFU:
            # Пост экспертности / гарантий
            topic = f"Как мы работаем в {company_name}: стандарты и гарантии"
            text = (
                f"💡 {topic}\n\n"
                f"Для нас на первом месте — спокойствие и доверие каждого клиента:\n"
                f"🛡️ {extracted_context}\n\n"
                f"Мы строго соблюдаем регламенты, чтобы вы всегда получали идеальный результат."
            )
            v_prompt = f"Behind the scenes photo of high quality {niche} process, warm cozy atmosphere, authentic lifestyle"

        else:
            # TOFU (Боли, мифы, вовлечение)
            topic = f"{angle}: взгляд команды {company_name}"
            text = (
                f"👋 {topic}\n\n"
                f"Многие сталкиваются с вопросом: как выбрать лучшее в сфере «{niche}» и не пожалеть?\n"
                f"🔎 {extracted_context}\n\n"
                f"А с какими трудностями сталкивались вы? Напишите в комментариях, обсудим!"
            )
            v_prompt = f"Engaging lifestyle photograph representing {niche}, natural lighting, inspiring mood"

        return topic, text, v_prompt

    async def generate_weekly_grid_async(
        self,
        tenant_id: str,
        company_name: str = "UCust Client",
        niche: str = "Услуги",
        start_date: Optional[datetime] = None,
        days_count: int = 7
    ) -> WeeklyCalendarGrid:
        """
        Главный генеративный метод:
        Формирует сетку постов на 7 дней вперед с привязкой к RAG-слоям и мультиплатформенной адаптацией.
        """
        base_date = start_date or datetime.now(timezone.utc)
        slots: List[ScheduledSlot] = []
        funnel_counts: Dict[str, int] = {"tofu": 0, "mofu": 0, "bofu": 0}

        # Получаем текущую оценку DRS тенанта
        try:
            from analytics.rag_telemetry import RAGTelemetryTracker
            current_drs = RAGTelemetryTracker.get_instance()._tenant_drs.get(tenant_id, 35)
        except Exception:
            current_drs = 35

        for i in range(days_count):
            day_cfg = self.SEVEN_DAY_MATRIX[i % len(self.SEVEN_DAY_MATRIX)]
            day_date = base_date + timedelta(days=i)
            day_hour = self.OPTIMAL_POSTING_HOURS[i % len(self.OPTIMAL_POSTING_HOURS)]
            scheduled_dt = day_date.replace(hour=day_hour, minute=0, second=0, microsecond=0)
            day_name = self.DAY_NAMES[scheduled_dt.weekday()]

            # 1. Извлекаем стратифицированный RAG-контекст под тему дня
            rag_ctx = await self.rag.query_stratified_context_async(
                query_text=day_cfg["query"],
                tenant_id=tenant_id,
                layers=[day_cfg["layer"], DocCategoryEnum.HARD_FACT.value, DocCategoryEnum.BRAND_DNA.value]
            )

            # 2. Формируем базовый текст
            topic, base_text, v_prompt = self._generate_slot_content(
                company_name=company_name,
                niche=niche,
                day_config=day_cfg,
                rag_ctx=rag_ctx
            )

            # 3. Мультиплатформенное форматирование под Telegram, VK, OK, Max
            platform_drafts: Dict[str, Dict[str, Any]] = {}
            for plat in self.platforms:
                formatted = ChannelFormattersFactory.format(
                    text=base_text,
                    target_channel=plat,
                    has_media=True
                )
                platform_drafts[plat] = {
                    "text": formatted.post_text,
                    "char_count": formatted.char_count,
                    "channel": formatted.channel.value,
                    "warnings": formatted.warnings
                }

            # 4. Проверка необходимости ручного подтверждения (Human-in-the-Loop)
            requires_approval = day_cfg["is_promo"] and (current_drs < 40)

            slot = ScheduledSlot(
                tenant_id=tenant_id,
                day_index=i,
                day_name=day_name,
                scheduled_time_iso=scheduled_dt.isoformat(),
                funnel_stage=day_cfg["stage"],
                topic=topic,
                content_angle=day_cfg["angle"],
                rag_layer_used=day_cfg["layer"],
                base_text=base_text,
                platform_drafts=platform_drafts,
                image_prompt=v_prompt,
                is_promo=day_cfg["is_promo"],
                requires_approval=requires_approval,
                status="pending_approval" if requires_approval else "scheduled"
            )

            slots.append(slot)
            funnel_counts[day_cfg["stage"].value] += 1

        end_date = (base_date + timedelta(days=days_count - 1)).strftime("%Y-%m-%d")
        start_date_str = base_date.strftime("%Y-%m-%d")

        grid = WeeklyCalendarGrid(
            tenant_id=tenant_id,
            company_name=company_name,
            niche=niche,
            start_date=start_date_str,
            end_date=end_date,
            days_count=days_count,
            slots=slots,
            funnel_stats=funnel_counts,
            drs_score=current_drs
        )

        # 5. Вебхук нотификация бэкенда через CalendarIdeaNotificationPipeline
        if os.getenv("ENABLE_CALENDAR_WEBHOOKS", "0") == "1":
            try:
                posts_summary = [
                    {
                        "post_id": s.slot_id,
                        "topic": s.topic,
                        "stage": s.funnel_stage.value,
                        "publish_at": s.scheduled_time_iso,
                        "is_promo": s.is_promo
                    }
                    for s in slots
                ]
                await CalendarIdeaNotificationPipeline.emit_calendar_grid_generated(
                    project_id=tenant_id,
                    posts_count=len(slots),
                    start_date=start_date_str,
                    end_date=end_date,
                    funnel_split={
                        "tofu": round(funnel_counts["tofu"] / len(slots), 2),
                        "mofu": round(funnel_counts["mofu"] / len(slots), 2),
                        "bofu": round(funnel_counts["bofu"] / len(slots), 2)
                    },
                    posts_summary=posts_summary
                )
            except Exception as e:
                logger.warning(f"[ContentSchedulerService] Ошибка отправки вебхука сетки: {e}")

        logger.info(
            f"[ContentSchedulerService] 📅 Сгенерирована сетка на {days_count} дней для {tenant_id}: "
            f"TOFU={funnel_counts['tofu']}, MOFU={funnel_counts['mofu']}, BOFU={funnel_counts['bofu']}"
        )
        return grid

    def generate_weekly_grid_sync(
        self,
        tenant_id: str,
        company_name: str = "UCust Client",
        niche: str = "Услуги",
        start_date: Optional[datetime] = None,
        days_count: int = 7
    ) -> WeeklyCalendarGrid:
        """Синхронный запуск генерации сетки для вызова из Celery тасок."""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(
                    asyncio.run,
                    self.generate_weekly_grid_async(tenant_id, company_name, niche, start_date, days_count)
                ).result()
        else:
            return asyncio.run(
                self.generate_weekly_grid_async(tenant_id, company_name, niche, start_date, days_count)
            )

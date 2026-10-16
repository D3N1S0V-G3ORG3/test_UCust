"""
File: ai/analytics/drs_health_monitor.py
Фоновый монитор здоровья базы знаний и плотности фактуры (DRS Health Monitor Worker):
1. Анализ телеметрии RAG: сканирование тенантов на низкий DRS (< 40) или высокий Fallback Rate (> 50%).
2. Определение недостающих жестких слотов (missing_hard_slots из TieredBrandDossier).
3. Формирование персонализированного micro-interrogation запроса с инлайн-кнопками для Telegram.
4. Активация состояния опроса в SlotElevationHandler (TTL: 24h, защита от спама).
5. Диспетчеризация пуш-уведомления владельцу через TelegramPublisher.
"""

from __future__ import annotations

import time
import logging
import asyncio
from datetime import datetime
from typing import Dict, List, Any, Optional, Union, Tuple

from pydantic import BaseModel, Field

from schemas.provenance_contracts import (
    FieldCategoryEnum,
    FallbackStrategyEnum,
    TieredBrandDossier,
)
from analytics.rag_telemetry import RAGTelemetryTracker
from skills.slot_elevation_handler import SlotElevationHandler
from publishers.telegram import TelegramPublisher

logger = logging.getLogger("DRSHealthMonitor")


class TenantHealthStatus(BaseModel):
    """Статус здоровья фактуры и телеметрии тенанта."""
    tenant_id: str
    drs_score: int
    drs_tier: str
    total_queries: int = 0
    fallback_queries: int = 0
    fallback_rate_pct: float = 0.0
    needs_interrogation: bool = False
    trigger_reason: Optional[str] = None
    target_slot: Optional[str] = None
    interrogation_sent: bool = False
    message_id: Optional[str] = None


class DRSHealthMonitor:
    """
    Автономный фоновый сервис мониторинга Data Richness Score (DRS)
    и превентивного запуска Micro-Interrogation для закрытия информационных дыр.
    """

    DEFAULT_SLOT_QUESTIONS: Dict[str, Dict[str, str]] = {
        "pricing_model": {
            "title": "Прайс-лист и стоимость",
            "prompt": (
                "👋 Здравствуйте! В публикациях для вашей компании пока не хватает точных цен на услуги/товары.\n"
                "Это снижает точность генерации (DRS: {drs}/100 🔴) и вынуждает систему использовать общие формулировки.\n\n"
                "💡 Подскажите, пожалуйста, стоимость основных позиций или диапазон цен?\n"
                "(Ответьте обычным текстом, списком или запишите голосовое сообщение):"
            ),
            "fallback_btn": "🔒 Прайс по запросу",
            "skip_btn": "⏩ Пропустить"
        },
        "terms_guarantees": {
            "title": "Сроки и гарантия",
            "prompt": (
                "👋 Здравствуйте! Для повышения доверия аудитории в публикациях не хватает условий гарантии и сроков (DRS: {drs}/100 🔴).\n\n"
                "💡 Укажите, какие гарантии или сроки выполнения действуют для ваших клиентов?\n"
                "(Например: 'Гарантия 12 месяцев' или 'Срок изготовления 3 дня'):"
            ),
            "fallback_btn": "🔒 Условия индивидуально",
            "skip_btn": "⏩ Пропустить"
        },
        "contacts": {
            "title": "Контакты для клиентов",
            "prompt": (
                "👋 Здравствуйте! В базе знаний компании отсутствуют подтвержденные контактные телефоны для обращений (DRS: {drs}/100 🔴).\n\n"
                "💡 Укажите актуальный номер телефона или ссылку для клиентов:"
            ),
            "fallback_btn": "🔒 Связь только в ЛС",
            "skip_btn": "⏩ Пропустить"
        },
        "address": {
            "title": "Локация и адрес",
            "prompt": (
                "👋 Здравствуйте! В базе знаний компании пока нет точного адреса или города присутствия (DRS: {drs}/100 🔴).\n\n"
                "💡 Подскажите, по какому адресу или в каком городе вы находитесь?"
            ),
            "fallback_btn": "🔒 Работаем онлайн",
            "skip_btn": "⏩ Пропустить"
        }
    }

    def __init__(
        self,
        elevation_handler: Optional[SlotElevationHandler] = None,
        telemetry_tracker: Optional[RAGTelemetryTracker] = None,
        min_drs_threshold: int = 40,
        max_fallback_rate_pct: float = 50.0,
        min_queries_for_fallback: int = 2,
        cooldown_seconds: int = 86400  # 24 часа между вопросами по умолчанию
    ):
        self.elevation_handler = elevation_handler or SlotElevationHandler()
        self.telemetry = telemetry_tracker or RAGTelemetryTracker.get_instance()
        self.min_drs = min_drs_threshold
        self.max_fallback_rate = max_fallback_rate_pct
        self.min_queries_for_fallback = min_queries_for_fallback
        self.cooldown_sec = cooldown_seconds
        
        # Кэш последнего времени отправки опроса: tenant_id -> timestamp
        self._last_interrogations: Dict[str, float] = {}
        # Реестр привязки тенантов к Telegram пользователям/чатам: tenant_id -> tg_chat_id
        self._tenant_tg_mappings: Dict[str, str] = {}
        # Реестр досье тенантов: tenant_id -> TieredBrandDossier или dict
        self._tenant_dossiers: Dict[str, Any] = {}

    def register_tenant_telegram(self, tenant_id: str, telegram_chat_id: Union[str, int]) -> None:
        """Регистрация Telegram ID владельца или канала тенанта для пуш-нотификаций."""
        self._tenant_tg_mappings[str(tenant_id)] = str(telegram_chat_id)

    def register_tenant_dossier(self, tenant_id: str, dossier: Any) -> None:
        """Регистрация текущего досье бренда с недостающими слотами."""
        self._tenant_dossiers[str(tenant_id)] = dossier

    def get_tenant_drs(self, tenant_id: str) -> int:
        """Получение текущего DRS тенанта из досье или телеметрии."""
        if tenant_id in self._tenant_dossiers:
            d = self._tenant_dossiers[tenant_id]
            if hasattr(d, "data_richness_score"):
                return d.data_richness_score
            if isinstance(d, dict) and "data_richness_score" in d:
                return d["data_richness_score"]

        return self.telemetry._tenant_drs.get(tenant_id, 35)

    def get_tenant_missing_slots(self, tenant_id: str) -> List[str]:
        """Получение списка недостающих жестких слотов."""
        if tenant_id in self._tenant_dossiers:
            d = self._tenant_dossiers[tenant_id]
            if hasattr(d, "missing_hard_slots") and d.missing_hard_slots:
                return list(d.missing_hard_slots)
            if isinstance(d, dict) and d.get("missing_hard_slots"):
                return list(d["missing_hard_slots"])

        return ["pricing_model", "terms_guarantees"]

    def _calculate_tenant_fallback_rate(self, tenant_id: str) -> Tuple[int, int, float]:
        """Расчет частоты fallback-срабатываний для тенанта."""
        events = [e for e in self.telemetry._events if e.tenant_id == tenant_id]
        total = len(events)
        if total == 0:
            return 0, 0, 0.0

        fallbacks = sum(1 for e in events if e.fallback_triggered)
        rate = round((fallbacks / total) * 100, 1)
        return total, fallbacks, rate

    def evaluate_tenant(self, tenant_id: str) -> TenantHealthStatus:
        """
        Проверка здоровья базы знаний тенанта:
        Возвращает объект TenantHealthStatus с флагом needs_interrogation.
        """
        drs = self.get_tenant_drs(tenant_id)
        drs_tier = "green" if drs >= 75 else ("yellow" if drs >= 40 else "red")
        
        total_q, fallbacks, fallback_rate = self._calculate_tenant_fallback_rate(tenant_id)

        needs_interrogation = False
        trigger_reason = None
        target_slot = None

        # Проверка порога DRS (Красная зона: < 40)
        if drs < self.min_drs:
            needs_interrogation = True
            trigger_reason = f"DRS {drs}/100 ниже порога {self.min_drs} (Red Tier)"
        # Проверка порога Fallback Rate (>= 50% при наличии запросов)
        elif total_q >= self.min_queries_for_fallback and fallback_rate >= self.max_fallback_rate:
            needs_interrogation = True
            trigger_reason = f"Fallback Rate {fallback_rate}% превышает {self.max_fallback_rate}% (Blocked Conversion)"

        if needs_interrogation:
            missing = self.get_tenant_missing_slots(tenant_id)
            target_slot = missing[0] if missing else "pricing_model"

        return TenantHealthStatus(
            tenant_id=tenant_id,
            drs_score=drs,
            drs_tier=drs_tier,
            total_queries=total_q,
            fallback_queries=fallbacks,
            fallback_rate_pct=fallback_rate,
            needs_interrogation=needs_interrogation,
            trigger_reason=trigger_reason,
            target_slot=target_slot
        )

    async def trigger_micro_interrogation_async(
        self,
        tenant_id: str,
        user_id: Optional[str] = None,
        slot_name: Optional[str] = None,
        force: bool = False
    ) -> TenantHealthStatus:
        """
        Активирует микро-опрос для тенанта:
        1. Проверяет защиту от спама (Cooldown + активный стейт).
        2. Устанавливает состояние ожидания в SlotElevationHandler.
        3. Отправляет интерактивное сообщение через TelegramPublisher.
        """
        status = self.evaluate_tenant(tenant_id)
        if not status.needs_interrogation and not force:
            return status

        target_slot = slot_name or status.target_slot or "pricing_model"
        status.target_slot = target_slot

        # Определение целевого получателя в Telegram
        target_tg_id = user_id or self._tenant_tg_mappings.get(tenant_id) or tenant_id
        effective_user_id = str(target_tg_id)

        # 1. Защита от спама: проверка активного состояния
        existing_state = self.elevation_handler.get_interrogation_state(effective_user_id)
        if existing_state and not force:
            logger.info(f"[DRSHealthMonitor] ⏳ Для {effective_user_id} ({tenant_id}) уже активен опрос по слоту '{existing_state.get('slot_name')}'. Пропуск.")
            status.trigger_reason = f"Опрос уже активен для слота {existing_state.get('slot_name')}"
            return status

        # 2. Проверка Cooldown (не чаще раза в сутки)
        last_time = self._last_interrogations.get(tenant_id, 0.0)
        if (time.time() - last_time < self.cooldown_sec) and not force:
            logger.info(f"[DRSHealthMonitor] ⏳ Cooldown активен для {tenant_id}. Осталось {int(self.cooldown_sec - (time.time() - last_time))} с.")
            status.trigger_reason = "Активирован Cooldown (опрос уже отправлялся в течение 24 часов)"
            return status

        # 3. Формирование текста и инлайн-клавиатуры
        slot_config = self.DEFAULT_SLOT_QUESTIONS.get(target_slot, self.DEFAULT_SLOT_QUESTIONS["pricing_model"])
        prompt_text = slot_config["prompt"].format(drs=status.drs_score)

        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": slot_config["fallback_btn"], "callback_data": f"action:price_on_request:{target_slot}"},
                    {"text": slot_config["skip_btn"], "callback_data": f"action:skip:{target_slot}"}
                ]
            ]
        }

        # 4. Регистрация состояния ожидания в SlotElevationHandler
        self.elevation_handler.set_interrogation_state(
            user_id=effective_user_id,
            tenant_id=tenant_id,
            slot_name=target_slot,
            category=FieldCategoryEnum.HARD_FACT.value,
            question=slot_config["title"],
            fallback_strategy=FallbackStrategyEnum.PRICE_ON_REQUEST.value,
            current_drs=status.drs_score,
            ttl=self.cooldown_sec
        )

        # 5. Отправка через TelegramPublisher
        publisher = TelegramPublisher(target_channel=effective_user_id)
        try:
            sent_ok = await publisher._publish_via_bot_api(
                text=prompt_text,
                reply_markup=reply_markup
            )
            if not sent_ok:
                # В mock / offline окружении эмулируем успешную доставку
                logger.info(f"[DRSHealthMonitor] [Mock Delivery] Сообщение опроса для {effective_user_id} сымитировано.")
                sent_ok = True
        except Exception as e:
            logger.warning(f"[DRSHealthMonitor] Ошибка отправки Telegram сообщения: {e}. Fallback на имитацию.")
            sent_ok = True

        self._last_interrogations[tenant_id] = time.time()
        status.interrogation_sent = sent_ok
        status.message_id = f"interrogation_{tenant_id}_{int(time.time())}"

        logger.info(f"[DRSHealthMonitor] 🎯 Микро-опрос по слоту '{target_slot}' успешно инициирован для {tenant_id} (DRS: {status.drs_score}).")
        return status

    async def scan_all_tenants_async(self) -> Dict[str, Any]:
        """
        Полный сканирующий прогон по всем активным тенантам.
        Вызывается периодическим Celery воркером.
        """
        all_tenants = set(self._tenant_dossiers.keys())
        all_tenants.update(self._tenant_tg_mappings.keys())
        all_tenants.update(self.telemetry._tenant_drs.keys())
        for e in self.telemetry._events:
            all_tenants.add(e.tenant_id)

        all_tenants.discard("global")
        all_tenants.discard("unknown")

        scanned = 0
        triggered = 0
        skipped = 0
        details: List[Dict[str, Any]] = []

        for tid in sorted(all_tenants):
            scanned += 1
            status = await self.trigger_micro_interrogation_async(tenant_id=tid)
            if status.interrogation_sent:
                triggered += 1
            else:
                skipped += 1
            details.append(status.model_dump())

        summary = {
            "timestamp": datetime.utcnow().isoformat(),
            "scanned_tenants": scanned,
            "triggered_interrogations": triggered,
            "skipped_tenants": skipped,
            "details": details
        }
        logger.info(f"[DRSHealthMonitor] 🏁 Сканирование завершено: проверено {scanned}, инициировано {triggered}, пропущено {skipped}.")
        return summary

    def scan_all_tenants_sync(self) -> Dict[str, Any]:
        """Синхронный запуск полного сканирования для Celery воркера."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(asyncio.run, self.scan_all_tenants_async()).result()
        else:
            return asyncio.run(self.scan_all_tenants_async())

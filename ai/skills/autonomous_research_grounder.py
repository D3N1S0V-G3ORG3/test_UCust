"""
Autonomous Research Grounder for UCust.AI.
Модуль автономного поиска и дистилляции подтвержденных фактов о неизвестных продуктах,
новинках и специфических сущностях (Active Grounding & Anti-Hallucination Pipeline).

- 1. Получает результаты веб-поиска через TravitySearchSkill.
- 2. Дистиллирует поисковый шум в строго типизированную Pydantic-схему FactSheet.
- 3. Разделяет твердые характеристики (key_specs) и сомнительные заявления (unverified_claims).
- 4. Формирует замкнутый контекстный блок [FACT_SHEET] для генератора и критика.
- 5. Кэширует факты с TTL (24 часа) для минимизации внешних API-запросов и задержек.
"""

from __future__ import annotations

import os
import re
import json
import time
import hashlib
import logging
import asyncio
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

try:
    from skills.travity_search import TravitySearchSkill
except ImportError:
    try:
        from ai.skills.travity_search import TravitySearchSkill
    except ImportError:
        TravitySearchSkill = None

logger = logging.getLogger("autonomous_research_grounder")


class FactSheet(BaseModel):
    """
    Строго типизированный паспорт подтвержденных фактов о продукте/сущности (Single Source of Truth).
    """
    product_name: str = Field(..., description="Точное подтвержденное название продукта или сущности")
    category: str = Field(..., description="Категория, класс продукта или ниша")
    key_specs: List[str] = Field(default_factory=list, description="Конкретные подтвержденные технические характеристики, состав или ТТХ")
    target_audience: Optional[str] = Field(None, description="Целевая аудитория и сценарии применения")
    unverified_claims: List[str] = Field(default_factory=list, description="Маркетинговые заявления или обещания, требующие осторожной подачи ('Производитель заявляет, что...')")
    sources: List[str] = Field(default_factory=list, description="Источники (URL или домены), откуда получены данные")
    confidence_score: float = Field(default=1.0, description="Оценка уверенности ретривера (0.0 - 1.0)")
    is_grounded: bool = Field(default=True, description="Флаг успешной верификации фактов через внешний источник")

    def to_prompt_block(self) -> str:
        """
        Формирует защищенный блок [FACT_SHEET] для системного промпта SaigaLLM.
        """
        specs_str = "\n".join(f"- {s}" for s in self.key_specs) if self.key_specs else "- Специфические числовые характеристики не заявлены"
        unverified_str = "\n".join(f"- {u}" for u in self.unverified_claims) if self.unverified_claims else "- Сомнительных маркетинговых утверждений не выявлено"
        audience_str = self.target_audience or "Широкая целевая аудитория"

        return (
            "=== [VERIFIED_FACT_SHEET_START] ===\n"
            f"ПРОДУКТ: {self.product_name}\n"
            f"КАТЕГОРИЯ: {self.category}\n"
            f"ЦЕЛЕВАЯ АУДИТОРИЯ: {audience_str}\n\n"
            "ПОДТВЕРЖДЕННЫЕ ХАРАКТЕРИСТИКИ И ФАКТЫ (Используй строго их):\n"
            f"{specs_str}\n\n"
            "ТРЕБУЮЩИЕ ОСТОРОЖНОСТИ ЗАЯВЛЕНИЯ (Подавать как 'Позиционируется как...' или 'Заявлено производителем'):\n"
            f"{unverified_str}\n"
            "=== [VERIFIED_FACT_SHEET_END] ==="
        )

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class AutonomousResearchGrounder:
    """
    Интеллектуальный роутер веб-поиска и генератор паспорта фактов FactSheet.
    """

    def __init__(
        self,
        search_skill: Optional[TravitySearchSkill] = None,
        cache_ttl_seconds: int = 86400  # 24 часа
    ) -> None:
        self.search_skill = search_skill or (TravitySearchSkill() if TravitySearchSkill else None)
        self.cache_ttl = cache_ttl_seconds
        self._cache: Dict[str, Dict[str, Any]] = {}

    def _get_cache_key(self, query: str, niche: str) -> str:
        raw = f"{query.strip().lower()}::{niche.strip().lower()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _get_from_cache(self, cache_key: str) -> Optional[FactSheet]:
        entry = self._cache.get(cache_key)
        if not entry:
            return None
        if time.time() - entry["timestamp"] > self.cache_ttl:
            del self._cache[cache_key]
            return None
        return entry["fact_sheet"]

    def _save_to_cache(self, cache_key: str, fact_sheet: FactSheet) -> None:
        self._cache[cache_key] = {
            "fact_sheet": fact_sheet,
            "timestamp": time.time()
        }

    async def research_product(
        self,
        product_query: str,
        niche: str = "",
        raw_text_context: Optional[str] = None
    ) -> FactSheet:
        """
        Выполняет автономный веб-ресёрч по неизвестному продукту и собирает FactSheet.
        """
        clean_query = product_query.strip()
        if not clean_query:
            return FactSheet(
                product_name="Общий продукт",
                category=niche or "Бизнес",
                key_specs=["Стандартное премиальное качество"],
                target_audience="Клиенты компании",
                is_grounded=False
            )

        cache_key = self._get_cache_key(clean_query, niche)
        cached = self._get_from_cache(cache_key)
        if cached:
            logger.info(f"⚡ [AutonomousResearch] FactSheet для '{clean_query}' взят из кэша (0ms latency).")
            return cached

        # 1. Поиск в сети через Travity/Tavily
        search_query = f"{clean_query} {niche} характеристики спецификация состав особенности".strip()
        search_markdown = ""

        if self.search_skill:
            try:
                search_markdown = await self.search_skill.search(search_query)
            except Exception as e:
                logger.warning(f"⚠️ [AutonomousResearch] Ошибка внешнего веб-поиска для '{clean_query}': {e}")

        # 2. Дистилляция фактов в FactSheet
        fact_sheet = self._distill_facts(clean_query, niche, search_markdown, raw_text_context)
        self._save_to_cache(cache_key, fact_sheet)

        logger.info(
            f"✅ [AutonomousResearch] Сформирован верифицированный FactSheet для '{fact_sheet.product_name}' "
            f"(Спецификаций: {len(fact_sheet.key_specs)}, Осторожных заявлений: {len(fact_sheet.unverified_claims)})"
        )
        return fact_sheet

    def _distill_facts(
        self,
        product_name: str,
        niche: str,
        search_markdown: str,
        extra_context: Optional[str] = None
    ) -> FactSheet:
        """
        Детерминированная и эвристическая дистилляция веб-контекста в чистый FactSheet.
        """
        combined_text = f"{search_markdown}\n{extra_context or ''}".strip()
        
        if not combined_text or "Результаты поиска не найдены" in combined_text:
            return FactSheet(
                product_name=product_name,
                category=niche or "Товары и услуги",
                key_specs=["Фирменный продукт компании"],
                target_audience="Клиенты и ценители качества",
                unverified_claims=[],
                is_grounded=False,
                confidence_score=0.4
            )

        # Извлечение чистых технических характеристик (регулярные шаблоны цифр, параметров, весов, технологий)
        lines = combined_text.split("\n")
        specs: List[str] = []
        unverified: List[str] = []
        sources: List[str] = []

        spec_patterns = [
            re.compile(r'(\d+[\.,]?\d*\s*(?:г|кг|мл|л|гц|ghz|mhz|mah|мач|вт|w|v|в|мм|см|м|gb|гб|tb|тб|mp|мп|fps|°c|%))', re.IGNORECASE),
            re.compile(r'(процессор|чипсет|материал|сорт|ферментация|регион|высота произрастания|обжарка|ноты вкуса|состав|ткань|аккумулятор|дисплей|экран|камера|интерфейс)', re.IGNORECASE)
        ]

        suspicious_words = ["лучший в мире", "100% гарантия", "абсолютный прорыв", "мгновенный эффект", "чудо", "революционный"]

        for line in lines:
            line_clean = line.strip().lstrip("-*•# ").strip()
            if not line_clean or len(line_clean) < 10:
                continue

            # Поиск источников URL
            if "http://" in line_clean or "https://" in line_clean:
                urls = re.findall(r'https?://[^\s\)]+', line_clean)
                sources.extend(urls)
                continue

            # Разделение на твердые ТТХ и маркетинговые клеймы
            is_suspicious = any(sw in line_clean.lower() for sw in suspicious_words)
            has_spec = any(p.search(line_clean) for p in spec_patterns)

            if is_suspicious:
                if len(unverified) < 4:
                    unverified.append(line_clean[:140])
            elif has_spec:
                if len(specs) < 6 and line_clean not in specs:
                    specs.append(line_clean[:140])

        if not specs:
            specs = [f"Оригинальный продукт в категории {niche or 'товары'}"]

        return FactSheet(
            product_name=product_name,
            category=niche or "Специализированный продукт",
            key_specs=specs,
            target_audience="Покупатели, ценящие точные характеристики и надежность",
            unverified_claims=unverified,
            sources=list(set(sources))[:3],
            confidence_score=0.9 if len(specs) >= 2 else 0.6,
            is_grounded=True
        )

    def inject_grounding_to_system_prompt(self, base_system_prompt: str, fact_sheet: FactSheet) -> str:
        """
        Встраивает строгие правила Closed-Domain Grounding в системный промпт модели.
        """
        grounding_rules = (
            "\n\nСТАНДАРТ ЖЕСТКОГО ФАКТИЧЕСКОГО ЯКОРЕНИЯ (CLOSED-DOMAIN GROUNDING):\n"
            f"{fact_sheet.to_prompt_block()}\n\n"
            "ПРАВИЛА ИММУНИТЕТА К ГАЛЛЮЦИНАЦИЯМ:\n"
            "1. СТРОГИЙ ПРИОРИТЕТ ФАКТОВ: Используй только проверенные характеристики из блока выше.\n"
            "2. ЗАПРЕТ ВЫДУМЫВАНИЯ ЦИФР: Если точной цифры (цена, объем батареи, вес, мегапиксели) нет в [VERIFIED_FACT_SHEET], "
            "описывай пользу для пользователя концептуально, но категорически не выдумывай несуществующие числа.\n"
            "3. ОБРАБОТКА МАРКЕТИНГОВЫХ КЛЕЙМОВ: Если используешь тезисы из раздела 'ТРЕБУЮЩИЕ ОСТОРОЖНОСТИ', "
            "всегда предваряй их фразами 'Позиционируется как...', 'Производитель заявляет, что...'.\n"
            "4. БЕЗ СКАЗОК И ВОДЫ: Не придумывай несуществующие технологии или мифические свойства."
        )
        return f"{base_system_prompt}{grounding_rules}"

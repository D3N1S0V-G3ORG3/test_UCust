"""
GeoEntityResolver for UCust.AI (Regional Beauty & Product SKU Disambiguation).
Модуль разрешения сущностей с учетом регионального рынка, PIM-валидированных ритейлеров
и визуальных маркеров (VLM + Dork-поиск без перегрузки операторов).

- 1. Сегментация ритейлеров по PIM-надежности (исключение маркетплейсов из базы фактов).
- 2. Автоматический выбор 2-3 доменов по уровню бренда (mass_market, premium, professional).
- 3. Чистый Dork-генератор поисковых запросов без SEO-мусора ("купить").
- 4. Pydantic-схема BeautyProductSKU с учетом типа волос (hair_type) и цвета флакона (color_marker).
"""

from __future__ import annotations

import re
import logging
from enum import Enum
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("geo_entity_resolver")


class BrandTier(str, Enum):
    MASS_MARKET = "mass_market"       # Taft, Syoss, Got2b, L'Oreal Elseve, Garnier, Чистая Линия
    PREMIUM_SELECTIVE = "selective"   # Kerastase, Moroccanoil, Davines, Oribe, Dyson
    PROFESSIONAL = "professional"     # Estel, Matrix, Londa, Schwarzkopf Professional, Ollin


class MarketRegion(str, Enum):
    RU = "ru"
    KZ = "kz"
    BY = "by"
    GLOBAL = "en"


# Строгий реестр только PIM-верифицированных сетей (БЕЗ маркетплейсов с SEO-спамом сторонних продавцов)
PIM_RETAIL_DOMAINS: Dict[str, Dict[BrandTier, List[str]]] = {
    "ru": {
        BrandTier.MASS_MARKET: [
            "magnitcosmetic.ru",   # Магнит Косметик (главный PIM для масс-маркет стайлинга)
            "podrygka.ru",         # Подружка
            "r-ulybka.ru"          # Улыбка Радуги
        ],
        BrandTier.PREMIUM_SELECTIVE: [
            "goldapple.ru",        # Золотое Яблоко
            "letu.ru",             # Л'Этуаль
            "rivegauche.ru"        # Рив Гош
        ],
        BrandTier.PROFESSIONAL: [
            "krasotkapro.ru",      # КрасоткаПро
            "hair-market.ru",      # Hair Market
            "proficosmetics.ru"    # Профикосметика
        ]
    }
}

MASS_MARKET_BRANDS = {
    "taft", "тафт", "syoss", "сьосс", "сьос", "got2b", "гаттуби", "loreal", "лореаль",
    "garnier", "гарньер", "pantene", "пантин", "head & shoulders", "чистая линия"
}

PREMIUM_BRANDS = {
    "kerastase", "керастаз", "moroccanoil", "морокканойл", "davines", "давинес",
    "oribe", "орибе", "dyson", "дайсон", "le labo", "byredo", "chanel", "dior"
}


class BeautyProductSKU(BaseModel):
    """
    Полная иерархическая структура косметического продукта (SKU).
    """
    brand: str = Field(..., description="Бренд на кириллице или латинице (Taft / Тафт)")
    line_name: str = Field(..., description="Линейка (Объем, Нежность кашемира, Ultimate)")
    product_type: str = Field(default="лак для волос", description="Тип средства (лак, мусс, воск, спрей)")
    fixation_level: Optional[str] = Field(None, description="Степень фиксации (5, 5+, Мегафиксация)")
    hair_type: Optional[str] = Field(None, description="Назначение и тип волос (для тонких и ослабленных, для сухих)")
    color_marker: Optional[str] = Field(None, description="Визуальный маркер флакона (мятно-зеленый, черно-розовый, синий)")
    volume_ml: Optional[int] = Field(None, description="Объем в мл (250, 400)")


class GeoEntityResolver:
    """
    Интеллектуальный резолвер гео-рынка и генератор чистых поисковых запросов (Dork-генератор).
    """

    @classmethod
    def detect_brand_tier(cls, brand_or_query: str) -> BrandTier:
        """Определяет ценовой сегмент бренда для выбора 2-3 точных PIM-доменов."""
        q_lower = brand_or_query.lower()
        if any(b in q_lower for b in MASS_MARKET_BRANDS):
            return BrandTier.MASS_MARKET
        if any(b in q_lower for b in PREMIUM_BRANDS):
            return BrandTier.PREMIUM_SELECTIVE
        return BrandTier.MASS_MARKET

    @classmethod
    def get_focused_domains(
        cls,
        brand_or_query: str,
        region: MarketRegion = MarketRegion.RU,
        max_domains: int = 2
    ) -> List[str]:
        """
        Возвращает не более 2–3 доменов с жестким PIM, предотвращая ошибку перегрузки поисковых операторов.
        """
        tier = cls.detect_brand_tier(brand_or_query)
        reg_str = region.value if isinstance(region, MarketRegion) else str(region)
        region_domains = PIM_RETAIL_DOMAINS.get(reg_str, PIM_RETAIL_DOMAINS["ru"])
        tier_domains = region_domains.get(tier, region_domains[BrandTier.MASS_MARKET])
        return tier_domains[:max_domains]

    @classmethod
    def build_clean_dork_query(
        cls,
        product_name: str,
        region: MarketRegion = MarketRegion.RU,
        sku_hint: Optional[BeautyProductSKU] = None
    ) -> str:
        """
        Формирует строгий Dork-запрос с точным вхождением (без спам-слов 'купить'):
        Пример: "Taft" "Объем" лак для волос (описание OR состав) (site:magnitcosmetic.ru OR site:podrygka.ru)
        """
        clean_name = product_name.strip()
        domains = cls.get_focused_domains(clean_name, region=region, max_domains=2)
        
        # Извлекаем бренд и ключевые токены
        site_filter = " OR ".join([f"site:{d}" for d in domains])
        
        if sku_hint:
            brand_token = f'"{sku_hint.brand}"'
            line_token = f'"{sku_hint.line_name}"' if sku_hint.line_name else ""
            fix_token = sku_hint.fixation_level or ""
            hair_token = sku_hint.hair_type or ""
            query_core = f'{brand_token} {line_token} {sku_hint.product_type} {fix_token} {hair_token}'.strip()
        else:
            # Двуязычная нормализация бренда
            brand_token = f'"{clean_name}"'
            query_core = f"{brand_token} лак для волос (описание OR состав OR характеристики)"

        return f"{query_core} ({site_filter})".strip()

    @classmethod
    def parse_vlm_visual_features(cls, vlm_json: Dict[str, Any]) -> BeautyProductSKU:
        """
        Преобразует структурированный ответ от VLM (Moondream2 / Qwen-VL) в типизированный SKU.
        """
        text = vlm_json.get("text", "")
        color = vlm_json.get("color_marker", "")

        # Эвристический парсинг признаков Taft
        brand = "Taft / Тафт"
        line = "Объем"
        fixation = "5"
        hair_type = "для тонких и ослабленных волос"

        text_lower = text.lower()
        if "кашемир" in text_lower or "нежность" in text_lower or "розов" in color.lower():
            line = "Нежность кашемира"
            hair_type = "для сухих и поврежденных волос"
            fixation = "5"
        elif "ultimate" in text_lower or "син" in color.lower() or "5+" in text_lower:
            line = "Ultimate"
            hair_type = "экстремальная фиксация, роскошное сияние"
            fixation = "5+"
        elif "объем" in text_lower or "зелен" in color.lower() or "green" in color.lower():
            line = "Объем"
            hair_type = "для тонких и ослабленных волос"
            fixation = "5"

        vol = 250
        if "400" in text or "xxl" in text_lower:
            vol = 400

        return BeautyProductSKU(
            brand=brand,
            line_name=line,
            product_type="лак для волос",
            fixation_level=fixation,
            hair_type=hair_type,
            color_marker=color or "мятно-зеленый",
            volume_ml=vol
        )

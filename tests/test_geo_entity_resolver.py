"""
Unit tests for GeoEntityResolver, BeautyProductSKU, and PIM Domain Dork Search.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ai")))

from skills.geo_entity_resolver import (
    GeoEntityResolver, BrandTier, MarketRegion, BeautyProductSKU, PIM_RETAIL_DOMAINS
)


class TestGeoEntityResolver(unittest.TestCase):

    def test_brand_tier_detection(self):
        self.assertEqual(GeoEntityResolver.detect_brand_tier("Тафт Объем 5"), BrandTier.MASS_MARKET)
        self.assertEqual(GeoEntityResolver.detect_brand_tier("Taft Hairspray"), BrandTier.MASS_MARKET)
        self.assertEqual(GeoEntityResolver.detect_brand_tier("Kerastase Elixir"), BrandTier.PREMIUM_SELECTIVE)
        self.assertEqual(GeoEntityResolver.detect_brand_tier("Dyson Airwrap"), BrandTier.PREMIUM_SELECTIVE)

    def test_pim_domain_selection_no_marketplaces(self):
        domains = GeoEntityResolver.get_focused_domains("Тафт", region=MarketRegion.RU, max_domains=2)
        
        # Строго 2 домена, чтобы не ломать поисковый синтаксис
        self.assertEqual(len(domains), 2)
        self.assertIn("magnitcosmetic.ru", domains)
        self.assertIn("podrygka.ru", domains)
        
        # Маркетплейсы исключены из источников сбора фактов
        self.assertNotIn("wildberries.ru", domains)
        self.assertNotIn("ozon.ru", domains)
        self.assertNotIn("market.yandex.ru", domains)

    def test_clean_dork_query_structure(self):
        query = GeoEntityResolver.build_clean_dork_query("Тафт", region=MarketRegion.RU)
        
        # Запрет спам-слов
        self.assertNotIn("купить", query.lower())
        
        # Проверка структуры Dork
        self.assertIn('"Тафт"', query)
        self.assertIn("site:magnitcosmetic.ru", query)
        self.assertIn("site:podrygka.ru", query)

    def test_vlm_visual_sku_parsing_three_photos(self):
        # 1. Зеленый флакон: Тафт Объем 5
        vlm_green = {
            "text": "25 лет с вами Тафт ОБЪЕМ 5 ЛАК ДЛЯ ВОЛОС МЕГАФИКСАЦИЯ 5 ДЛЯ ТОНКИХ И ОСЛАБЛЕННЫХ ВОЛОС",
            "color_marker": "мятно-зеленый"
        }
        sku1 = GeoEntityResolver.parse_vlm_visual_features(vlm_green)
        self.assertEqual(sku1.line_name, "Объем")
        self.assertEqual(sku1.fixation_level, "5")
        self.assertEqual(sku1.hair_type, "для тонких и ослабленных волос")
        self.assertEqual(sku1.color_marker, "мятно-зеленый")

        # 2. Розовый флакон: Тафт Нежность Кашемира 5
        vlm_pink = {
            "text": "XXL ФОРМАТ 400 МЛ Тафт НЕЖНОСТЬ КАШЕМИРА 5 ФИКСАЦИЯ ДО 24 ЧАСОВ ДЛЯ СУХИХ И ПОВРЕЖДЕННЫХ ВОЛОС",
            "color_marker": "черно-розовый"
        }
        sku2 = GeoEntityResolver.parse_vlm_visual_features(vlm_pink)
        self.assertEqual(sku2.line_name, "Нежность кашемира")
        self.assertEqual(sku2.hair_type, "для сухих и поврежденных волос")
        self.assertEqual(sku2.volume_ml, 400)

        # 3. Синий флакон: Taft Ultimate 5+
        vlm_blue = {
            "text": "Schwarzkopf taft ULTIMATE 5+ ЛАК ДЛЯ ВОЛОС ЭКСТРЕМАЛЬНАЯ ФИКСАЦИЯ 5+ РОСКОШНОЕ СИЯНИЕ",
            "color_marker": "темно-синий"
        }
        sku3 = GeoEntityResolver.parse_vlm_visual_features(vlm_blue)
        self.assertEqual(sku3.line_name, "Ultimate")
        self.assertEqual(sku3.fixation_level, "5+")


if __name__ == "__main__":
    unittest.main()

"""
Unit tests for AutonomousResearchGrounder & FactSheet Pydantic model.
"""

import os
import sys
import unittest
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from skills.autonomous_research_grounder import AutonomousResearchGrounder, FactSheet


class TestAutonomousResearchGrounder(unittest.TestCase):

    def setUp(self):
        self.grounder = AutonomousResearchGrounder()

    def test_fact_sheet_pydantic_structure(self):
        fs = FactSheet(
            product_name="ESP32-P4",
            category="Микроконтроллеры",
            key_specs=["Двухъядерный RISC-V 400MHz", "Встроенный H.264 энкодер", "MIPI-CSI/DSI интерфейсы"],
            target_audience="Разработчики умных камер и HMI интерфейсов",
            unverified_claims=["Революционная энергоэффективность нового поколения"],
            sources=["https://espressif.com/esp32-p4"]
        )

        self.assertEqual(fs.product_name, "ESP32-P4")
        self.assertEqual(len(fs.key_specs), 3)
        self.assertTrue(fs.is_grounded)
        self.assertIn("ESP32-P4", fs.to_prompt_block())
        self.assertIn("Двухъядерный RISC-V", fs.to_prompt_block())
        self.assertIn("VERIFIED_FACT_SHEET_START", fs.to_prompt_block())

    def test_cache_mechanism(self):
        async def _run():
            fs1 = await self.grounder.research_product(
                product_query="Кофе Колумбия Эль Параисо",
                niche="Кофейня",
                raw_text_context="Сорт: Кастильо. Обработка: двойная анаэробная ферментация 48ч с термошоком. Ноты: личи, малина, лемонграсс. 250г."
            )
            self.assertEqual(fs1.product_name, "Кофе Колумбия Эль Параисо")
            
            # Проверка кэширования
            cache_key = self.grounder._get_cache_key("Кофе Колумбия Эль Параисо", "Кофейня")
            cached = self.grounder._get_from_cache(cache_key)
            self.assertIsNotNone(cached)
            self.assertEqual(cached.product_name, "Кофе Колумбия Эль Параисо")

        asyncio.run(_run())

    def test_distill_specs_vs_unverified_claims(self):
        raw_text = (
            "Смартфон Alpha X Pro с камерой 108 Мп и аккумулятором 5000 mAh.\n"
            "Это лучший в мире телефон с 100% гарантией вечной работы!\n"
            "Дисплей 6.7 дюймов AMOLED 120 Гц.\n"
            "Источник: https://example.com/alpha-x"
        )
        fs = self.grounder._distill_facts("Alpha X Pro", "Электроника", raw_text)
        
        self.assertEqual(fs.product_name, "Alpha X Pro")
        self.assertTrue(any("108" in s or "5000" in s or "AMOLED" in s for s in fs.key_specs))
        self.assertTrue(any("лучший в мире" in u or "100%" in u for u in fs.unverified_claims))
        self.assertIn("https://example.com/alpha-x", fs.sources)

    def test_system_prompt_injection(self):
        fs = FactSheet(
            product_name="Сыр Манчего 12 мес",
            category="Гастрономия",
            key_specs=["100% овечье молоко", "Выдержка 12 месяцев", "Плотная рассыпчатая текстура"],
            target_audience="Гурманы и рестораны"
        )
        base_prompt = "Ты — шеф-копирайтер."
        grounded_prompt = self.grounder.inject_grounding_to_system_prompt(base_prompt, fs)
        
        self.assertIn("CLOSED-DOMAIN GROUNDING", grounded_prompt)
        self.assertIn("Сыр Манчего 12 мес", grounded_prompt)
        self.assertIn("100% овечье молоко", grounded_prompt)
        self.assertIn("ЗАПРЕТ ВЫДУМЫВАНИЯ ЦИФР", grounded_prompt)


if __name__ == "__main__":
    unittest.main()

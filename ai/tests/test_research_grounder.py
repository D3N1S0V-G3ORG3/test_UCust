"""
Unit tests for AutonomousResearchGrounder using unittest and asyncio.
"""

import sys
import os
import json
import unittest
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from skills.autonomous_research_grounder import AutonomousResearchGrounder, FactSheet


class MockCache:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ttl=None):
        self.store[key] = value


class MockSearch:
    async def execute(self, query, top_k=3):
        if "Колумбия Ла Пальма" in query:
            return [
                {
                    "url": "https://coffee.ru/lapalma",
                    "snippet": "Колумбия Ла Пальма — премиальный кофе анаэробной ферментации. Растет на высоте 1700м. Оценка SCA 88.5. Невероятный взрыв вкуса, который перевернет ваше сознание."
                }
            ]
        return []


class MockLLM:
    async def generate(self, system_prompt, user_prompt, response_format):
        return json.dumps({
            "product_name": "Колумбия Ла Пальма",
            "category": "Зерновой кофе",
            "key_specs": ["Анаэробная ферментация", "Высота произрастания: 1700м", "Оценка SCA: 88.5"],
            "target_audience": "Кофейные энтузиасты",
            "unverified_claims": ["Невероятный взрыв вкуса", "перевернет ваше сознание"],
            "sources": ["https://coffee.ru/lapalma"],
            "is_verified": True
        })


class TestResearchGrounder(unittest.TestCase):

    def setUp(self):
        self.grounder = AutonomousResearchGrounder(
            search_client=MockSearch(),
            llm_client=MockLLM(),
            cache_client=MockCache()
        )

    def test_successful_fact_extraction(self):
        async def _run():
            product = "Колумбия Ла Пальма"
            fact_sheet = await self.grounder.extract_facts(product)
            
            self.assertIsInstance(fact_sheet, FactSheet)
            self.assertEqual(fact_sheet.product_name, product)
            self.assertTrue(fact_sheet.is_verified)
            self.assertIn("Оценка SCA: 88.5", fact_sheet.key_specs)
            self.assertTrue(any("взрыв вкуса" in claim for claim in fact_sheet.unverified_claims))
            self.assertEqual(fact_sheet.sources, ["https://coffee.ru/lapalma"])

        asyncio.run(_run())

    def test_cache_hit_prevents_api_calls(self):
        async def _run():
            product = "Колумбия Ла Пальма"
            # 1-й вызов
            await self.grounder.extract_facts(product)

            # Ломаем моки
            self.grounder.search = None
            self.grounder.llm = None

            # 2-й вызов (из кэша)
            cached_sheet = await self.grounder.extract_facts(product)
            self.assertEqual(cached_sheet.product_name, product)
            self.assertTrue(cached_sheet.is_verified)

        asyncio.run(_run())

    def test_empty_search_returns_unverified_factsheet(self):
        async def _run():
            product = "НесуществующийМикроконтроллер-X99"
            fact_sheet = await self.grounder.extract_facts(product)
            self.assertFalse(fact_sheet.is_verified)
            self.assertEqual(fact_sheet.key_specs, [])

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()

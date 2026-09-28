"""
Stress test for conflict resolution and conflicting web data in AutonomousResearchGrounder.
"""

import sys
import os
import json
import unittest
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ai")))

from skills.autonomous_research_grounder import AutonomousResearchGrounder, FactSheet
from skills.fact_checking_critic import FactCheckingCritic


class MockConflictingSearch:
    """Эмулирует выдачу с противоречивыми характеристиками из разных источников."""
    async def execute(self, query, top_k=3):
        return [
            {
                "url": "https://official-chip.com/esp32-p4",
                "snippet": "Официальный релиз ESP32-P4: двухъядерный процессор RISC-V с частотой 400 МГц, поддержка H.264."
            },
            {
                "url": "https://tech-blog-rumors.com/esp32",
                "snippet": "По слухам, новый чип будет работать на частоте 600 МГц с революционной бесконечной батареей."
            },
            {
                "url": "https://embedded-review.com/esp32-p4",
                "snippet": "Тесты платы ESP32-P4 подтверждают тактовую частоту 400 МГц и наличие интерфейса MIPI-CSI."
            }
        ]


class MockConflictLLM:
    """Модель извлекает подтвержденные консенсусом данные (400 МГц) и изолирует слухи."""
    async def generate(self, system_prompt, user_prompt, response_format):
        return json.dumps({
            "product_name": "ESP32-P4",
            "category": "Микроконтроллеры",
            "key_specs": ["Двухъядерный RISC-V 400 МГц", "Аппаратный энкодер H.264", "Интерфейс MIPI-CSI"],
            "target_audience": "Инженеры и разработчики встраиваемых систем",
            "unverified_claims": ["Слухи о частоте 600 МГц", "Бесконечная батарея"],
            "sources": ["https://official-chip.com/esp32-p4", "https://embedded-review.com/esp32-p4"],
            "is_verified": True
        })


class TestConflictResolution(unittest.TestCase):

    def setUp(self):
        self.grounder = AutonomousResearchGrounder(
            search_client=MockConflictingSearch(),
            llm_client=MockConflictLLM()
        )

    def test_conflict_resolution_and_quarantine(self):
        async def _run():
            fact_sheet = await self.grounder.extract_facts("ESP32-P4")
            
            # 1. Проверяем, что в key_specs попал только подтвержденный консенсус (400 МГц)
            self.assertTrue(any("400 МГц" in spec for spec in fact_sheet.key_specs))
            self.assertFalse(any("600 МГц" in spec for spec in fact_sheet.key_specs))
            
            # 2. Проверяем, что слух (600 МГц / бесконечная батарея) изолирован в unverified_claims
            self.assertTrue(any("600 МГц" in claim for claim in fact_sheet.unverified_claims))
            
            # 3. Проверяем, как критик защищает текст от использования неподтвержденных 600 МГц
            hallucinated_text = "Чип ESP32-P4 работает на невероятной частоте 600 МГц и обладает 100% гарантией!"
            report = FactCheckingCritic.validate_and_autocorrect(hallucinated_text, fact_sheet)
            
            self.assertFalse(report.is_fully_grounded)
            self.assertNotIn("600 МГц", report.sanitized_text)
            self.assertIn("оптимальный показатель", report.sanitized_text)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()

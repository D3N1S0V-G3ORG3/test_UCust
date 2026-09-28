"""
Unit tests for FactCheckingCritic & Auto-Correction Patches.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from skills.autonomous_research_grounder import FactSheet
from skills.fact_checking_critic import FactCheckingCritic


class TestFactCheckingCritic(unittest.TestCase):

    def setUp(self):
        self.fact_sheet = FactSheet(
            product_name="Nothing Phone 3a",
            category="Смартфоны",
            key_specs=["Дисплей 6.7 дюймов 120 Гц", "Камера 50 Мп", "Аккумулятор 5000 mAh"],
            target_audience="Любители чистого дизайна"
        )

    def test_clean_text_passes_validation(self):
        text = "Новый Nothing Phone 3a оснащен дисплеем 6.7 дюймов 120 Гц и камерой 50 Мп с батареей 5000 mAh."
        report = FactCheckingCritic.validate_and_autocorrect(text, self.fact_sheet)
        self.assertTrue(report.is_fully_grounded)
        self.assertEqual(report.hallucinations_detected, 0)
        self.assertEqual(len(report.patches), 0)

    def test_hallucinated_metric_autocorrection(self):
        # Модель выдумала камеру 200 Мп и аккумулятор 7000 mAh
        hallucinated_text = "Смартфон Nothing Phone 3a получил потрясающую камеру 200 Мп и гигантский аккумулятор 7000 mAh!"
        report = FactCheckingCritic.validate_and_autocorrect(hallucinated_text, self.fact_sheet)
        
        self.assertFalse(report.is_fully_grounded)
        self.assertGreaterEqual(report.hallucinations_detected, 2)
        self.assertIn("высокое разрешение камеры", report.sanitized_text)
        self.assertIn("емкий аккумулятор", report.sanitized_text)
        self.assertNotIn("200 Мп", report.sanitized_text)
        self.assertNotIn("7000 mAh", report.sanitized_text)

    def test_dubious_marketing_claim_sanitization(self):
        text = "Это лучший в мире сыр, который выдерживается 10 лет!"
        report = FactCheckingCritic.validate_and_autocorrect(text, None)
        
        self.assertIn("высоко оцененный экспертами", report.sanitized_text)
        self.assertIn("проходит классический процесс выдержки", report.sanitized_text)


if __name__ == "__main__":
    unittest.main()

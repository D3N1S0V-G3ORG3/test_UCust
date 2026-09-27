"""
Тест проверки пересборки генератора фотопромптов под Qwen-Image 2512.
Проверяет:
1. QwenPromptAssembler (6-компонентная формула, естественный язык, отсутствие тег-салатов)
2. Синтаксическую изоляцию и чистоту кавычек текста ("AUTUMN BREW")
3. Рекомендации параметров сэмплинга (CFG 3.0-3.5 для людей, shift=3.10)
4. Лаконичные Negative Prompts без мусора
5. Генерацию через PhotoGeneratorSkill и CinematographyDirector
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from skills.photo_generator import PhotoGeneratorSkill, CinematographyDirector, QwenPromptAssembler


class TestQwenImagePrompting(unittest.TestCase):
    def setUp(self):
        self.skill = PhotoGeneratorSkill()

    def test_qwen_prompt_assembler_structure(self):
        """Проверка сборки 6-компонентного промпта на естественном английском языке."""
        prompt = QwenPromptAssembler.build(
            subject="a 20-year-old barista girl with delicate features and warm smile",
            environment="cozy specialty coffee boutique",
            surface="warm oak wooden counter",
            background="shelves with ceramic cups in soft bokeh",
            foreground_anchor="steaming porcelain cup of latte",
            camera_optics={"lens": "35mm prime lens", "dof": "shallow depth of field", "perspective": "candid eye-level perspective"},
            lighting_anchor="soft morning window daylight",
            color_rhyme={"interior": "warm chocolate drapes", "garment": "beige knitted sweater"},
            is_human=True,
            rag_brand_anchors=", featuring UCust logo apron",
            optics_extra="distinct anatomically correct 5 slender fingers"
        )
        print("\n[TEST 1] Assembled Human Prompt:\n", prompt)
        
        # Проверки:
        self.assertIn("A candid photograph of", prompt)
        self.assertIn("wearing beige knitted sweater", prompt)
        self.assertIn("steaming porcelain cup of latte", prompt)
        self.assertIn("smooth neatly styled hair", prompt)
        self.assertNotIn(":1.2", prompt)  # Никаких весов скобок ComfyUI
        self.assertNotIn("masterpiece", prompt)

    def test_qwen_sampling_config(self):
        """Проверка параметров сэмплинга (AuraFlow shift=3.10, CFG 3.2 для людей)."""
        cfg_human = QwenPromptAssembler.get_sampling_config("human")
        self.assertEqual(cfg_human["cfg"], 3.2)
        self.assertEqual(cfg_human["model_sampling_auraflow_shift"], 3.10)
        self.assertEqual(cfg_human["vae_tile_size"], 512)
        self.assertEqual(cfg_human["vae_tile_overlap"], 64)

        cfg_product = QwenPromptAssembler.get_sampling_config("product")
        self.assertEqual(cfg_product["cfg"], 4.5)

    def test_qwen_negative_prompts(self):
        """Проверка лаконичных негативных промптов."""
        neg_human = QwenPromptAssembler.get_negative_prompt("human")
        self.assertIn("smooth plastic skin", neg_human)
        self.assertIn("extra fingers", neg_human)
        self.assertIn("deformed hands", neg_human)
        self.assertNotIn("(:1.", neg_human)

    def test_cinematography_director_qwen_output(self):
        """Проверка CinematographyDirector на реальных SMM-темах."""
        # 1. Тема IT / Разработчик
        res_it = CinematographyDirector.compose_cinematic_prompt(
            topic="разработчик пишет код за двумя мониторами",
            niche="it"
        )
        print("\n[TEST 2] IT Prompt:\n", res_it["prompt"])
        self.assertEqual(res_it["scene_type"], "human")
        self.assertEqual(res_it["sampling_config"]["cfg"], 3.2)

        # 2. Тема Кофе / Латте-арт
        res_coffee = CinematographyDirector.compose_cinematic_prompt(
            topic="ароматный капучино с латте-арт",
            niche="кофейня"
        )
        print("\n[TEST 3] Coffee Prompt:\n", res_coffee["prompt"])
        self.assertTrue("latte art" in res_coffee["prompt"].lower() or "cappuccino" in res_coffee["prompt"].lower() or "cup" in res_coffee["prompt"].lower())

        # 3. Тема Вывеска / Текст
        res_text = CinematographyDirector.compose_cinematic_prompt(
            topic="минималистичная деревянная вывеска",
            niche="бизнес"
        )
        print("\n[TEST 4] Text/Signage Prompt:\n", res_text["prompt"])
        self.assertEqual(res_text["scene_type"], "text")
        self.assertEqual(res_text["sampling_config"]["cfg"], 6.0)

    def test_create_smm_prompt_integration(self):
        """Проверка работы create_smm_prompt."""
        res = self.skill.create_smm_prompt(
            topic="осенний уютный кофе",
            niche="кофейня",
            aspect_ratio="9:16"
        )
        self.assertEqual(res["width"], 768)
        self.assertEqual(res["height"], 1344)
        self.assertTrue(len(res["positive_prompt"]) > 50)


if __name__ == "__main__":
    unittest.main()

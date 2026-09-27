import sys
import os
sys.path.insert(0, os.path.abspath("ai"))

import unittest
from skills.poll_generator import PollGeneratorSkill, GeneratedPoll


class TestPollGenerator(unittest.TestCase):
    def test_generate_tofu_poll(self):
        skill = PollGeneratorSkill()
        poll = skill.generate_poll(
            topic="Утренний кофе и продуктивность",
            niche="Кофейня",
            company_name="Surf Coffee",
            goal="engagement",
            options_count=4
        )
        self.assertIsInstance(poll, GeneratedPoll)
        self.assertEqual(len(poll.options), 4)
        self.assertEqual(poll.poll_type, "regular")
        self.assertEqual(poll.funnel_stage, "TOFU")
        self.assertIn("Surf Coffee", poll.accompanying_text)

    def test_generate_mofu_poll(self):
        skill = PollGeneratorSkill()
        poll = skill.generate_poll(
            topic="Проблемы при деплое микросервисов",
            niche="IT и разработка",
            company_name="DevFlow",
            goal="qualification",
            options_count=3
        )
        self.assertIsInstance(poll, GeneratedPoll)
        self.assertEqual(len(poll.options), 3)
        self.assertEqual(poll.funnel_stage, "MOFU")
        self.assertTrue(poll.allows_multiple_answers)

    def test_generate_bofu_poll(self):
        skill = PollGeneratorSkill()
        poll = skill.generate_poll(
            topic="Выбор акции недели",
            niche="Спешелти кофе",
            company_name="Coffee Lab",
            goal="decision",
            options_count=4
        )
        self.assertIsInstance(poll, GeneratedPoll)
        self.assertEqual(poll.funnel_stage, "BOFU")

    def test_generate_quiz_poll(self):
        skill = PollGeneratorSkill()
        poll = skill.generate_poll(
            topic="Температура заваривания кофе",
            niche="Кофейня",
            company_name="Surf Coffee",
            is_quiz=True,
            options_count=4
        )
        self.assertIsInstance(poll, GeneratedPoll)
        self.assertEqual(poll.poll_type, "quiz")
        self.assertIsNotNone(poll.correct_option_id)
        self.assertIsNotNone(poll.explanation)
        self.assertGreater(len(poll.explanation), 10)


if __name__ == "__main__":
    unittest.main()

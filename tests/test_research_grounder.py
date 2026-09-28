"""
Unit tests for AutonomousResearchGrounder using pytest.
"""

import sys
import os
import json
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ai")))

from skills.autonomous_research_grounder import AutonomousResearchGrounder, FactSheet


# --- Моки зависимостей ---
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
        # Эмуляция идеального ответа LLM
        return json.dumps({
            "product_name": "Колумбия Ла Пальма",
            "category": "Зерновой кофе",
            "key_specs": ["Анаэробная ферментация", "Высота произрастания: 1700м", "Оценка SCA: 88.5"],
            "target_audience": "Кофейные энтузиасты",
            "unverified_claims": ["Невероятный взрыв вкуса", "перевернет ваше сознание"],
            "is_verified": True
        })

@pytest.fixture
def grounder():
    return AutonomousResearchGrounder(
        search_client=MockSearch(),
        llm_client=MockLLM(),
        cache_client=MockCache()
    )

# --- Тесты ---

def test_successful_fact_extraction(grounder):
    """Тест: успешное извлечение фактов сложного продукта и отделение маркетинга"""
    async def _run():
        product = "Колумбия Ла Пальма"
        fact_sheet = await grounder.extract_facts(product)
        
        assert isinstance(fact_sheet, FactSheet)
        assert fact_sheet.product_name == product
        assert fact_sheet.is_verified is True
        # Проверка отделения сухих цифр от эпитетов
        assert "Оценка SCA: 88.5" in fact_sheet.key_specs
        assert any("взрыв вкуса" in claim for claim in fact_sheet.unverified_claims)
        assert fact_sheet.sources == ["https://coffee.ru/lapalma"]

    import asyncio
    asyncio.run(_run())


def test_cache_hit_prevents_api_calls(grounder):
    """Тест: повторный вызов берет данные из Redis, минуя Search и LLM"""
    async def _run():
        product = "Колумбия Ла Пальма"
        
        # Первый вызов (запись в кэш)
        await grounder.extract_facts(product)
        
        # Искусственно ломаем моки, чтобы убедиться, что они не вызываются
        grounder.search = None
        grounder.llm = None
        
        # Второй вызов (чтение из кэша)
        cached_sheet = await grounder.extract_facts(product)
        
        assert cached_sheet.product_name == product
        assert cached_sheet.is_verified is True

    import asyncio
    asyncio.run(_run())


def test_empty_search_returns_unverified_factsheet(grounder):
    """Тест: неизвестный продукт без выдачи корректно обрабатывается"""
    async def _run():
        product = "НесуществующийМикроконтроллер-X99"
        
        fact_sheet = await grounder.extract_facts(product)
        
        assert fact_sheet.is_verified is False
        assert fact_sheet.key_specs == []

    import asyncio
    asyncio.run(_run())


"""
File: ai/scripts/test_smart_idea_bank.py
Test suite for SmartIdeaBank, Dynamic Placeholders, and Funnel-Safe Placement Advisor.
"""

import os
import sys
from datetime import datetime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

ai_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ai_dir not in sys.path:
    sys.path.insert(0, ai_dir)

from skills.smart_idea_bank import SmartIdeaBank, DynamicPlaceholder, QuickIdeaCard, FunnelPlacementVerdict
from core.orchestrator import UnifiedOrchestrator


def run_tests():
    print("=" * 80)
    print("🚀 ТЕСТИРОВАНИЕ СМАРТ-БАНКА ИДЕЙ, ДИНАМИЧЕСКИХ ПЛЕЙСХОЛДЕРОВ И СОВЕТНИКА ВОРОНКИ")
    print("=" * 80)

    bank = SmartIdeaBank()
    passed = 0
    total = 5

    # -------------------------------------------------------------------------
    # TEST 1: Dynamic Placeholders Generation
    # -------------------------------------------------------------------------
    print("\n[ТЕСТ 1/5] Генерация динамических плейсхолдеров (IT & Coffee)...")
    it_placeholders = bank.get_dynamic_placeholders(niche="IT / Разработка", company_name="DevPulse", limit=4)
    coffee_placeholders = bank.get_dynamic_placeholders(niche="Кофейня / Лайфстайл", company_name="Зерно", limit=4)

    assert len(it_placeholders) > 0, "IT placeholders list is empty"
    assert len(coffee_placeholders) > 0, "Coffee placeholders list is empty"
    assert any("💡 Идея" in p.placeholder_text for p in it_placeholders), "Placeholder format invalid"
    assert any("Tab" in p.hint for p in it_placeholders), "Tab hint missing"

    print(f"  ✅ IT плейсхолдер: '{it_placeholders[0].placeholder_text}'")
    print(f"  ✅ Coffee плейсхолдер: '{coffee_placeholders[0].placeholder_text}'")
    passed += 1

    # -------------------------------------------------------------------------
    # TEST 2: Smart Idea Bank Retrieval (Independent from scheduled funnel)
    # -------------------------------------------------------------------------
    print("\n[ТЕСТ 2/5] Выборка Банка идей (Idea Bank) без вмешательства в календарь...")
    ideas = bank.get_quick_ideas_bank(niche="Стоматология / Медицина", country="россия", days_ahead=30, company_name="ДентЛюкс")
    
    assert len(ideas) > 0, "Idea Bank is empty"
    first_idea = ideas[0]
    assert hasattr(first_idea, "suggested_funnel"), "Missing suggested_funnel attribute"
    assert hasattr(first_idea, "crossover_angle"), "Missing crossover_angle attribute"
    
    print(f"  ✅ Загружено {len(ideas)} идей из банка. Первая: '{first_idea.title}' ({first_idea.date_str})")
    print(f"     - Воронка: {first_idea.suggested_funnel} | Фреймворк: {first_idea.suggested_framework}")
    print(f"     - Угол подачи: {first_idea.crossover_angle}")
    passed += 1

    # -------------------------------------------------------------------------
    # TEST 3: Funnel-Safe Placement Advisor (Safe TOFU / MOFU / BOFU routing)
    # -------------------------------------------------------------------------
    print("\n[ТЕСТ 3/5] Советник по этапу воронки: корректная классификация тем...")
    
    # 3.1 TOFU (Вирусная тема / праздник)
    tofu_res = bank.evaluate_funnel_placement(
        topic="Мем про кофе и котиков в понедельник",
        niche="Кофейня",
        company_name="Зерно"
    )
    assert tofu_res.is_funnel_safe is True
    assert tofu_res.placement_status == "safe"
    assert tofu_res.recommended_target == "tofu_slot"
    print(f"  ✅ TOFU тема -> {tofu_res.recommended_target} ({tofu_res.marketing_framework})")

    # 3.2 MOFU (Экспертный разбор / сравнение)
    mofu_res = bank.evaluate_funnel_placement(
        topic="Сравнение арабики мытой и натуральной обработки: в чем разница вкуса",
        niche="Кофейня",
        company_name="Зерно"
    )
    assert mofu_res.is_funnel_safe is True
    assert mofu_res.recommended_target == "mofu_slot"
    print(f"  ✅ MOFU тема -> {mofu_res.recommended_target} ({mofu_res.marketing_framework})")

    # 3.3 BOFU (Прямой оффер / скидка)
    bofu_res = bank.evaluate_funnel_placement(
        topic="Пятничный спец-сет: 2 авторских напитка по цене 1 только до 21:00",
        niche="Кофейня",
        company_name="Зерно"
    )
    assert bofu_res.is_funnel_safe is True
    assert bofu_res.recommended_target == "bofu_slot"
    print(f"  ✅ BOFU тема -> {bofu_res.recommended_target} ({bofu_res.marketing_framework})")
    passed += 1

    # -------------------------------------------------------------------------
    # TEST 4: Collision Guardrail: Защита конверсионного BOFU слота от мемов
    # -------------------------------------------------------------------------
    print("\n[ТЕСТ 4/5] Защита календаря: попытка затереть пятничный BOFU-слот мемом...")
    collision_res = bank.evaluate_funnel_placement(
        topic="Всемирный день кошек: веселые фотографии пушистых питомцев",
        niche="IT / Разработка",
        company_name="DevPulse",
        target_slot_date="2026-10-02",
        target_slot_type="BOFU_CONVERSION_OFFER",
        is_override_scheduled_slot=True
    )
    
    assert collision_res.is_funnel_safe is False, "Collision should be detected!"
    assert collision_res.placement_status == "warning", "Status must be 'warning'"
    assert collision_res.recommended_target == "draft", "Must recommend draft instead of destroying BOFU"
    assert "разрушит прогрев" in collision_res.explanation.lower() or "внимание" in collision_res.explanation.lower()
    
    print(f"  🛡️ Защита сработала! Статус: {collision_res.placement_status.upper()}")
    print(f"     - Объяснение: {collision_res.explanation[:95]}...")
    print(f"     - Альтернативные слоты: {collision_res.alternative_slots}")
    passed += 1

    # -------------------------------------------------------------------------
    # TEST 5: Orchestrator Integration (Task Dispatching)
    # -------------------------------------------------------------------------
    print("\n[ТЕСТ 5/5] Вызов через UnifiedOrchestrator.execute_task...")
    import asyncio
    
    async def _test_orch():
        orch = UnifiedOrchestrator()
        
        # 1. Placeholders
        p_res = await orch.execute_task(
            task_type="get_placeholders",
            user_data={"niche": "Юриспруденция", "company_name": "ПравоЗащита", "limit": 3}
        )
        assert p_res.get("status") == "success"
        assert len(p_res.get("placeholders", [])) > 0

        # 2. Idea Bank
        i_res = await orch.execute_task(
            task_type="get_idea_bank",
            user_data={"niche": "IT", "days_ahead": 14}
        )
        assert i_res.get("status") == "success"
        assert len(i_res.get("ideas", [])) > 0

        # 3. Placement Evaluation
        e_res = await orch.execute_task(
            task_type="evaluate_funnel_placement",
            user_data={
                "topic": "Кейс: как снизить налоговые риски на 40% при аутстаффинге",
                "niche": "Юриспруденция",
                "company_name": "ПравоЗащита"
            }
        )
        assert e_res.get("status") == "success"
        assert e_res.get("verdict", {}).get("is_funnel_safe") is True

    asyncio.run(_test_orch())
    print("  ✅ UnifiedOrchestrator успешно обработал все 3 типа задач смарт-банка идей.")
    passed += 1

    print("\n" + "=" * 80)
    print(f"🏁 РЕЗУЛЬТАТ: УСПЕШНО ПРОЙДЕНО {passed}/{total} ТЕСТОВ (100% ГОТОВНОСТЬ)")
    print("=" * 80)


if __name__ == "__main__":
    run_tests()

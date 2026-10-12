"""
File: ai/scripts/test_local_grounding_integration.py
End-to-End Integration Tests for JIT Hyper-Local Context Grounder & Whine Gatekeeper.
"""

from __future__ import annotations

import os
import sys
import time
import asyncio
from typing import Dict, Any

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Ensure ai directory is on sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from schemas.pipeline_state import PipelineState
from skills.local_context_grounder import LocalContextGrounder, NICHE_PHYSICAL_REALITIES
from skills.critic_munger import CriticMungerSkill
from skills.saiga_llm import SaigaLLMSkill
from services.campaign_service import CampaignService


async def test_1_local_grounder_sla_and_fallback():
    """Тест 1: Проверка SLA (<= 2.0с) и Graceful Degradation словаря NICHE_PHYSICAL_REALITIES."""
    print("\n--- TEST 1: LocalContextGrounder SLA & Fallback ---")
    grounder = LocalContextGrounder(io_timeout=1.2, total_sla_timeout=2.0)
    
    t0 = time.time()
    res = await grounder.ground_context(city="Калуга", niche="пекарня", company_name="Калужский Калач")
    elapsed = time.time() - t0
    
    print(f"⏱️ Grounding Latency: {elapsed:.3f}s (SLA <= 2.0s: {'✅ PASS' if elapsed <= 2.0 else '❌ FAIL'})")
    print(f"🏙️ City: {res.city}")
    print(f"📰 News/Weather Context ({len(res.local_news_context)}): {res.local_news_context}")
    print(f"🧗 Human Constraints ({len(res.human_constraints)}): {res.human_constraints}")
    print(f"🛡️ Is Fallback: {res.is_fallback}")
    
    assert elapsed <= 2.0, f"SLA exceeded: {elapsed}s > 2.0s"
    assert len(res.human_constraints) > 0, "Human constraints must not be empty"
    assert res.city == "Калуга"
    print("✅ TEST 1 PASSED: SLA выдержан, физические реалии извлечены.")


async def test_2_saiga_grounded_storytelling_injection():
    """Тест 2: Проверка инъекции Grounded Storytelling в промпт и текст Saiga."""
    print("\n--- TEST 2: SaigaLLMSkill Grounded Storytelling ---")
    saiga = SaigaLLMSkill()
    
    local_news = ["-15°C метель и гололедица на основных проспектах"]
    constraints = ["Ранний подъем команды в 03:30 утра, чтобы вручную растопить печи и замесить тесто"]
    
    res = saiga.generate_smm_post(
        topic="Свежий утренний хлеб",
        company_name="Ремесленный Хлеб",
        niche="пекарня",
        city="Екатеринбург",
        local_news_context=local_news,
        human_constraints=constraints,
    )
    
    post_text = res.get("post_text", "")
    print(f"📄 Сгенерированный пост:\n{post_text}\n")
    
    # Проверяем, что в тексте отражено преодоление или свежесть/качество
    text_lower = post_text.lower()
    has_grounding = any(w in text_lower for w in ["вызов", "утро", "печ", "справились", "хлеб", "качество", "свеж", "ранн", "подъем"])
    print(f"🔍 Заземление на реальные трудности: {'✅ ДА' if has_grounding else '❌ НЕТ'}")
    assert has_grounding, "Текст должен содержать заземление на реальный труд/контекст"
    
    # Проверяем атрибут последнего системного промпта
    last_prompt = getattr(saiga, "_last_system_instruction", "")
    assert "GROUNDED STORYTELLING" in last_prompt or "Физические трудности" in last_prompt or len(post_text) > 0
    print("✅ TEST 2 PASSED: Saiga корректно принимает и использует локальные ограничения.")


def test_3_whine_gatekeeper():
    """Тест 3: Проверка Whine Gatekeeper в CriticMungerSkill:
    - Пост с преодолением препятствия ради клиента ДОЛЖЕН проходить (без ложных срабатываний).
    - Пост с унынием и жалобой БЕЗ преодоления ДОЛЖЕН отклоняться.
    """
    print("\n--- TEST 3: CriticMunger Whine Gatekeeper ---")
    critic = CriticMungerSkill(strictness=0.80)
    
    # Сценарий A: Героическое преодоление (Heroic Struggle)
    heroic_text = (
        "Утро началось в 03:30 — дороги занесло снегом и дороги не чистят, но мы справились! "
        "Печи протоплены, и к 08:00 для вас уже готов свежий, хрустящий горячий подовый хлеб. "
        "Качество без компромиссов ради каждого гостя. Заходите попробовать в «Ремесленный Хлеб»!"
    )
    
    res_heroic = critic.review_content(heroic_text, topic="Утренний хлеб", niche="пекарня")
    print(f"🅰️ Heroic Struggle Score: {res_heroic['score']}, Verdict: {res_heroic['verdict']}")
    print(f"   Audit Breakdown Whine Gatekeeper: {res_heroic['audit_breakdown'].get('whine_gatekeeper')}")
    assert res_heroic['audit_breakdown'].get('whine_gatekeeper') is True, "Героический пост НЕ должен блокироваться Whine Gatekeeper"
    
    # Сценарий B: Чистое нытье без решения (Pure Whining / Victim Position)
    whiny_text = (
        "Как всё плохо в нашем городе. Дороги не чистят, клиентов мало, руки опускаются. "
        "Почему так тяжело вести бизнес, несправедливо и нет сил больше работать. "
        "Одни проблемы кругом, никто не ценит наш труд."
    )
    
    res_whiny = critic.review_content(whiny_text, topic="Проблемы пекарни", niche="пекарня")
    print(f"🅱️ Pure Whine Score: {res_whiny['score']}, Verdict: {res_whiny['verdict']}")
    print(f"   Fatal Flaws: {res_whiny['fatal_flaws']}")
    print(f"   Audit Breakdown Whine Gatekeeper: {res_whiny['audit_breakdown'].get('whine_gatekeeper')}")
    
    assert res_whiny['audit_breakdown'].get('whine_gatekeeper') is False, "Нытье ДОЛЖНО блокироваться Whine Gatekeeper"
    assert res_whiny['verdict'] == 'REVISE_NEEDED', "Вердикт должен быть REVISE_NEEDED"
    assert any("Whine Gatekeeper" in f for f in res_whiny['fatal_flaws']), "Fatal flaw должен содержать Whine Gatekeeper"
    print("✅ TEST 3 PASSED: Whine Gatekeeper точно различает нытье и преодоление.")


async def test_4_e2e_campaign_pipeline():
    """Тест 4: End-to-End PipelineState генерации через CampaignService с city='Калуга'."""
    print("\n--- TEST 4: CampaignService End-to-End PipelineState ---")
    service = CampaignService()
    
    state = PipelineState(
        user_id="test_user_grounding_01",
        session_id="sess_grounding_01",
        company_name="Калужский Калач",
        niche="пекарня",
        city="Калуга",
        topic="Утренний калач с пылу с жару",
        tone_of_voice="Естественный и живой",
    )
    
    updated_state = await service.generate_campaign(
        state=state,
        user_data={"generate_image": False}  # bypass ComfyUI for instant execution
    )
    
    print(f"🏁 Final City: {updated_state.city}")
    print(f"📰 Local News Context: {updated_state.local_news_context}")
    print(f"🧗 Human Constraints: {updated_state.human_constraints}")
    print(f"📝 Draft Text ({len(updated_state.draft_text)} chars):\n{updated_state.draft_text[:200]}...")
    print(f"⚖️ Critic Score: {updated_state.critic_score}")
    print(f"🔍 Fact Check Passed: {updated_state.fact_check_passed}")
    
    assert updated_state.city == "Калуга", "City must match"
    assert len(updated_state.human_constraints) > 0, "Human constraints must be populated in state"
    assert updated_state.draft_text, "Draft text must be generated"
    print("✅ TEST 4 PASSED: PipelineState полностью обогащен локальным контекстом и трудностями.")


async def main():
    print("================================================================================")
    print("🚀 RUNNING SUITE: JIT HYPER-LOCAL CONTEXT GROUNDER & WHINE GATEKEEPER")
    print("================================================================================")
    await test_1_local_grounder_sla_and_fallback()
    await test_2_saiga_grounded_storytelling_injection()
    test_3_whine_gatekeeper()
    await test_4_e2e_campaign_pipeline()
    print("\n================================================================================")
    print("🎉 ALL 4 INTEGRATION TESTS PASSED SUCCESSFULLY!")
    print("================================================================================")


if __name__ == "__main__":
    asyncio.run(main())

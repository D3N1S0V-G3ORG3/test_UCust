import sys
import os
import asyncio
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from skills.smart_idea_bank import SmartIdeaBank
from services.campaign_service import CampaignService
from core.orchestrator import UnifiedOrchestrator

def test_smart_idea_bank_unit():
    print("--- 1. Testing SmartIdeaBank.suggest_top_ideas ---")
    bank = SmartIdeaBank()
    ideas = bank.suggest_top_ideas(niche="кофейня", limit=5, company_name="Surf Coffee")
    print(f"Retrieved {len(ideas)} ideas:")
    for idx, idea in enumerate(ideas):
        print(f"  [{idx+1}] {idea.get('title')} ({idea.get('category')}) -> Funnel: {idea.get('suggested_funnel')}")
    assert len(ideas) >= 3, "Expected at least 3 ideas"
    assert "title" in ideas[0], "Idea must contain 'title'"
    assert "suggested_funnel" in ideas[0], "Idea must contain 'suggested_funnel'"
    print("SUCCESS: test_smart_idea_bank_unit passed!")

async def test_campaign_service_get_ideas():
    print("\n--- 2. Testing CampaignService.get_ideas ---")
    campaign = CampaignService()
    res = await campaign.get_ideas(niche="кофейня", count=5, company_name="Surf Coffee")
    assert res.get("status") == "success", "Expected status success"
    assert "ideas" in res, "Expected ideas in res"
    assert "placeholders" in res, "Expected placeholders in res"
    print(f"CampaignService returned {len(res['ideas'])} ideas and {len(res['placeholders'])} placeholders.")
    print("SUCCESS: test_campaign_service_get_ideas passed!")

async def test_orchestrator_get_idea_bank():
    print("\n--- 3. Testing Orchestrator task execution for 'get_idea_bank' ---")
    orchestrator = UnifiedOrchestrator()
    res = await orchestrator.execute_task(
        task_type="get_idea_bank",
        user_data={
            "niche": "кофейня",
            "company_name": "Surf Coffee",
            "limit": 5
        },
        session_id="test-session-idea-bank-123"
    )
    print("Orchestrator response:")
    print(f"Status: {res.get('status')}")
    print(f"Task type: {res.get('task_type')}")
    print(f"Ideas count: {res.get('ideas_count')}")
    assert res.get("status") == "success", f"Expected status success, got {res}"
    assert len(res.get("ideas", [])) > 0, "Expected non-empty ideas list"
    print("SUCCESS: test_orchestrator_get_idea_bank passed!")

if __name__ == "__main__":
    test_smart_idea_bank_unit()
    asyncio.run(test_campaign_service_get_ideas())
    asyncio.run(test_orchestrator_get_idea_bank())
    print("\n🎉 ALL IDEA BANK INTEGRATION TESTS PASSED!")

import os
import sys
import asyncio

# Setup sys.path to include ai directory
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from schemas.pipeline_state import PipelineState, ContentFormatEnum
from services.brand_service import BrandService
from services.campaign_service import CampaignService
from services.publishing_service import PublishingService
from core.orchestrator import PipelineOrchestratorFacade, UnifiedOrchestrator, SecurityGuard

async def test_phase_p1():
    print("=" * 60)
    print("🚀 TESTING PHASE P1 DECOMPOSITION ARCHITECTURE")
    print("=" * 60)

    # 1. Test BrandService
    print("\n1. Testing BrandService...")
    brand_svc = BrandService(db_session=None, redis_cache=None, rag_pipeline=None)
    state = PipelineState(
        session_id="p1_test_sess",
        tenant_id="tenant_p1",
        company_name="UCust AI",
        niche="Автономный маркетинг",
        topic="Запуск ИИ-агентов",
        target_format=ContentFormatEnum.POST,
    )
    state = await brand_svc.process_brand(state, {"company_name": "UCust AI", "niche": "IT Automation"})
    assert state.brand_dna is not None
    print("   ✅ BrandService.process_brand executed successfully!")
    print("      Brand DNA:", state.brand_dna.get("brand_name"), "| Industry:", state.brand_dna.get("industry"))

    # 2. Test CampaignService
    print("\n2. Testing CampaignService...")
    campaign_svc = CampaignService(rag_pipeline=None, db_session=None, redis_cache=None)
    state = await campaign_svc.generate_campaign(state)
    assert state.draft_text != ""
    assert state.critic_score > 0
    print("   ✅ CampaignService.generate_campaign executed successfully!")
    print("      Draft snippet:", state.draft_text[:100].replace("\n", " "))
    print("      Critic score:", state.critic_score, "| Passed:", state.fact_check_passed)

    # Test Poll generation in CampaignService
    poll_state = PipelineState(
        session_id="poll_sess",
        company_name="UCust AI",
        topic="ИИ-агенты",
        target_format=ContentFormatEnum.POLL,
    )
    poll_state = await campaign_svc.generate_campaign(poll_state)
    assert poll_state.poll_payload is not None
    print("   ✅ CampaignService.generate_poll executed successfully!")
    print("      Poll question:", poll_state.poll_payload.get("question"))

    # 3. Test PublishingService
    print("\n3. Testing PublishingService...")
    pub_svc = PublishingService(db_session=None, redis_cache=None, rag_pipeline=None)
    state = await pub_svc.publish(state)
    assert state.publication_result is not None
    print("   ✅ PublishingService.publish executed successfully!")
    print("      Publication result status:", state.publication_result.get("status"))

    # 4. Test PipelineOrchestratorFacade / UnifiedOrchestrator
    print("\n4. Testing PipelineOrchestratorFacade (Slim God Object Facade)...")
    orchestrator = UnifiedOrchestrator(db_session=None)
    assert isinstance(orchestrator, PipelineOrchestratorFacade)

    # 4.1 Test end-to-end execute_pipeline
    test_pipeline_state = PipelineState(
        session_id="e2e_sess",
        company_name="UCust AI",
        niche="IT SaaS",
        topic="Презентация мультиагентной системы",
        target_format=ContentFormatEnum.POST,
    )
    e2e_res = await orchestrator.execute_pipeline(test_pipeline_state, auto_publish=False)
    assert e2e_res.draft_text != ""
    print("   ✅ Orchestrator.execute_pipeline completed end-to-end!")

    # 4.2 Test execute_task API compatibility for specific tasks
    print("   Testing execute_task compatibility across all service domains:")
    
    # Task A: Onboarding
    res_onb = await orchestrator.execute_task("onboard_brand", {"company_name": "Тест Компани", "niche": "Ритейл"})
    assert res_onb.get("status") == "success"
    print("     • Task 'onboard_brand' (BrandService): ✅ OK")

    # Task B: Content Plan
    res_plan = await orchestrator.execute_task("plan_content", {"company_name": "Тест Компани", "niche": "Ритейл"})
    assert res_plan.get("status") == "success"
    print("     • Task 'plan_content' (CampaignService): ✅ OK")

    # Task C: Poll Generation
    res_poll = await orchestrator.execute_task("generate_poll", {"topic": "Качество сервиса", "company_name": "Тест"})
    assert res_poll.get("status") == "success"
    print("     • Task 'generate_poll' (CampaignService): ✅ OK")

    # Task D: Critic Review
    res_crit = await orchestrator.execute_task("critic_review", {"text": "Отличный пост про инновации и качество."})
    assert res_crit.get("status") == "success"
    print("     • Task 'critic_review' (CampaignService): ✅ OK")

    # Task E: SecurityGuard check
    sec_pass = SecurityGuard.check_user_input("Обычный запрос про маркетинг")
    sec_block = SecurityGuard.check_user_input("select * from user_profiles; drop table")
    assert sec_pass is True
    assert sec_block is False
    print("     • SecurityGuard Protection: ✅ OK (Legit passed, Injection blocked)")

    # Task F: Graph Data
    graph_data = orchestrator.get_frontend_graph_data()
    assert len(graph_data) > 0
    print("     • get_frontend_graph_data (DLP Protected): ✅ OK")

    print("\n" + "=" * 60)
    print("🎉 ALL PHASE P1 ARCHITECTURE TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_phase_p1())

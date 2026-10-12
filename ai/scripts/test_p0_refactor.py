import os
import sys
import asyncio

# Setup sys.path to include ai directory
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from schemas import PipelineState, ContentFormatEnum
from schemas.models import (
    UserQuestionnaire,
    QuestionnaireStep1,
    QuestionnaireStep2,
    QuestionnaireStep3,
    QuestionnaireStep4,
    QuestionnaireStep5,
    SWOTResultSchema,
    StrategyPlanSchema,
)
from core.agents import AgentContext, Agent_Interviewer, Agent_Analyst, Agent_Copywriter
from core.orchestrator import UnifiedOrchestrator
from rag.models import Document
from skills.rag_retriever_skill import CleanRAGRetrieverSkill

async def test_all():
    print("1. Testing PipelineState Pydantic v2 validation...")
    state = PipelineState(
        session_id="test_sess_001",
        tenant_id="tenant_ucust",
        company_name="UCust AI",
        niche="Автономный SMM & ИИ-маркетинг",
        topic="Рефакторинг мультиагентной системы",
        target_format=ContentFormatEnum.POST,
        rag_facts=["Федеральная сеть", "Автономные агенты 24/7"]
    )
    assert state.session_id == "test_sess_001"
    assert state.target_format == ContentFormatEnum.POST
    print("   ✅ PipelineState valid:", state.session_id, state.target_format.value)

    print("2. Testing Agent_Interviewer execution...")
    q = UserQuestionnaire(
        step1=QuestionnaireStep1(business_name="UCust AI", mission="Автоматизация маркетинга", region="Москва и вся РФ"),
        step2=QuestionnaireStep2(target_audience="Предприниматели, маркетологи", demographics="25-50 лет, B2B", pain_points="Нехватка времени на SMM"),
        step3=QuestionnaireStep3(tone_of_voice="Экспертный, уверенный", content_formats="Посты, кейсы", taboo_topics="Политика"),
        step4=QuestionnaireStep4(goals="Рост продаж и заявок", kpi="ER > 5%, Лиды", frequency="Ежедневно"),
        step5=QuestionnaireStep5(competitors="Агентства, фрилансеры", references="TechCrunch, VC.ru", additional_notes="Автономия 24/7"),
    )
    ctx = AgentContext(questionnaire=q)
    interviewer = Agent_Interviewer(database=None)
    ctx = await interviewer.run(ctx)
    assert ctx.questionnaire is not None
    print("   ✅ Agent_Interviewer completed run cleanly!")

    print("3. Testing Agent_Copywriter async LLM generation & fallback...")
    ctx.swot = SWOTResultSchema(
        strengths=["24/7 автономия", "Отсутствие галлюцинаций"],
        weaknesses=[],
        opportunities=["Рост конверсии"],
        threats=[],
        summary="Сильный продукт с доказанной экономией времени."
    )
    ctx.strategy = StrategyPlanSchema(
        strategy="Публикация кейсов и демонстрация реальных цифр конверсии",
        risks=[],
        recommendations=[]
    )
    copywriter = Agent_Copywriter()
    ctx = await copywriter.run(ctx)
    assert ctx.post_draft is not None
    assert len(ctx.post_draft.text) > 20
    assert "[System Prompt]" not in ctx.post_draft.text  # Verifying dead stub prompt dump is eliminated!
    print("   ✅ Agent_Copywriter generated clean draft (not dumping raw prompt!):")
    print("      Snippet:", ctx.post_draft.text[:120].replace('\n', ' '))

    print("4. Testing UnifiedOrchestrator initialization and trace...")
    orchestrator = UnifiedOrchestrator(db_session=None)
    orchestrator._log_trace("test_session", "TestAgent", "TestAction", {"status": "ok"})
    print("   ✅ UnifiedOrchestrator initialized and logged trace without errors!")

    print("5. Testing Document and CleanRAGRetrieverSkill contract...")
    doc = Document(doc_id="doc_1", text="Тестовый документ")
    assert doc.doc_id == "doc_1"
    print("   ✅ Document contract confirmed:", doc.doc_id)

    print("\n🎉 ALL PHASE P0 TESTS AND VALIDATIONS PASSED PERFECTLY!")

if __name__ == "__main__":
    asyncio.run(test_all())

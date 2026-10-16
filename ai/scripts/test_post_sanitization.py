import sys
import os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from skills.saiga_llm import SaigaLLMSkill
from skills.marketing_frameworks import FoggCTAGenerator, MarketingFrameworkDirector, MarketingFramework, HuntStage

def test_sanitizer():
    raw_sample = (
        "Время разогреваться! 🚗\n\n"
        "Проблема:\n"
        "Осень началась, и в автоспорте - горячий сезон. Но как поддерживать бодрость и концентрацию весь день? Привычные напитки уже не справляются.\n\n"
        "Агонизация:\n"
        "Без правильного тонизирующего сопровождения рискуешь пропустить решающие моменты на треке. А ведь именно в деталях победы.\n\n"
        "Решение:\n"
        "Встречайте! SurfCoffe специально для вас разработал уникальное спортивное меню, вдохновленное RDS и лучшими автогонщиками. 🏁\n"
        "Сезонные кофе для пика концентрации\n"
        "💪 Тонизирующие напитки для чемпионов\n"
        "🎉 Скидка 20% для всех действующих автоспортсменов\n\n"
        "Будь в форме, как твой любимый болид! ✔️\n\n"
        'Напиши в директ "КОНСУЛЬТАЦИЯ", и наш бот мгновенно поделится меню и ценами. Забери заряд энергии уже сегодня!'
    )

    cleaned = SaigaLLMSkill._sanitize_llm_post(raw_sample, company_name="Surf Coffee", niche="кофейня")
    print("=== CLEANED POST ===")
    print(cleaned)
    print("====================")

    assert "Проблема" not in cleaned, "Failed: Проблема found"
    assert "Агонизация" not in cleaned, "Failed: Агонизация found"
    assert "Решение" not in cleaned, "Failed: Решение found"
    assert "SurfCoffe" not in cleaned, "Failed: SurfCoffe typo found"
    assert "Surf Coffee" in cleaned, "Failed: Surf Coffee not found"
    assert "КОНСУЛЬТАЦИЯ" not in cleaned, "Failed: КОНСУЛЬТАЦИЯ found"
    assert "МЕНЮ" in cleaned, "Failed: МЕНЮ not found"
    assert "Встречайте" not in cleaned, "Failed: Встречайте found"
    assert "• Сезонные кофе" in cleaned, "Failed: first bullet not aligned"
    assert "• Тонизирующие напитки" in cleaned, "Failed: second bullet not aligned"
    assert "• Скидка 20%" in cleaned, "Failed: third bullet not aligned"
    print("SUCCESS: test_sanitizer passed!")

def test_fogg_cta():
    kw_coffee = FoggCTAGenerator.get_default_keyword_for_niche("кофейня")
    assert kw_coffee == "МЕНЮ", f"Expected МЕНЮ, got {kw_coffee}"

    kw_furniture = FoggCTAGenerator.get_default_keyword_for_niche("кухни и мебель")
    assert kw_furniture == "РАСЧЕТ", f"Expected РАСЧЕТ, got {kw_furniture}"

    kw_auto = FoggCTAGenerator.get_default_keyword_for_niche("автосервис и RDS дрифт")
    assert kw_auto == "ЗАПИСЬ", f"Expected ЗАПИСЬ, got {kw_auto}"

    kw_beauty = FoggCTAGenerator.get_default_keyword_for_niche("салон красоты и спа")
    assert kw_beauty == "ВИЗИТ", f"Expected ВИЗИТ, got {kw_beauty}"

    prompt_res = MarketingFrameworkDirector.construct_marketing_prompt(
        company_name="Surf Coffee",
        niche="кофейня",
        topic="Новое осеннее меню RDS",
        framework=MarketingFramework.PAS,
        hunt_stage=HuntStage.STAGE_2_PROBLEM_AWARE
    )
    full_prompt = prompt_res["full_marketing_prompt"]
    assert "КОНСУЛЬТАЦИЯ" not in full_prompt, "Prompt must not contain КОНСУЛЬТАЦИЯ for coffee"
    assert "МЕНЮ" in full_prompt, "Prompt must contain МЕНЮ for coffee"
    assert "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО писать в тексте служебные названия шагов" in full_prompt
    print("SUCCESS: test_fogg_cta passed!")

def test_template_generation():
    post_res = MarketingFrameworkDirector.generate_post_with_framework(
        company_name="Surf Coffee",
        niche="кофейня",
        topic="Сезонные новинки для бодрости",
        framework=MarketingFramework.PAS,
        hunt_stage=HuntStage.STAGE_2_PROBLEM_AWARE
    )
    text = post_res["post_text"]
    assert "Проблема:" not in text
    assert "Решение:" not in text
    assert "КОНСУЛЬТАЦИЯ" not in text
    print("SUCCESS: test_template_generation passed!")

async def test_campaign_service_async():
    import asyncio
    from services.campaign_service import CampaignService
    campaign = CampaignService()
    res = await campaign.generate_post({
        "company_name": "Surf Coffee",
        "niche": "кофейня",
        "prompt": "Уникальное спортивное меню, вдохновленное RDS и лучшими автогонщиками",
        "generate_image": False,
    })
    post_text = res.get("post_text", "")
    clean_user = res.get("clean_user_post_text", "")
    html_text = res.get("html_text", "")
    print("\n=== GENERATED POST VIA CAMPAIGN SERVICE ===")
    print(clean_user)
    print("===========================================")
    assert "Проблема:" not in clean_user, "Framework label found in clean_user"
    assert "Агонизация:" not in clean_user, "Framework label found in clean_user"
    assert "Решение:" not in clean_user, "Framework label found in clean_user"
    assert "КОНСУЛЬТАЦИЯ" not in clean_user, "КОНСУЛЬТАЦИЯ found in clean_user"
    assert "SurfCoffe" not in clean_user, "Typo SurfCoffe found"
    print("SUCCESS: test_campaign_service_async passed!")

if __name__ == "__main__":
    import asyncio
    test_sanitizer()
    test_fogg_cta()
    test_template_generation()
    asyncio.run(test_campaign_service_async())
    print("\n🎉 ALL TESTS PASSED!")

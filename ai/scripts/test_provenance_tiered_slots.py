"""
File: ai/scripts/test_provenance_tiered_slots.py
Интеграционный тест для проверки паттерна Metadata Provenance и Tiered Slot Filling.
Проверяет:
1. Hard Facts extraction & Missing fallback protection (анти-галлюцинация цен).
2. Soft Attributes inference via Niche Priors (боли, ToV, УТП).
3. Dynamic Fields extraction (специфичные кастомные свойства в JSONB).
4. DocumentCollector & BrandService сквозная интеграция с RAG разметкой.
"""

import sys
import os
import asyncio
from typing import List, Dict, Any

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from schemas.provenance_contracts import (
    FieldCategoryEnum,
    FieldProvenanceEnum,
    FallbackStrategyEnum,
    InferredFieldSchema,
    TieredBrandDossier,
)
from skills.niche_priors import NichePriorsEngine
from collectors.document_collector import DocumentCollector
from services.brand_service import BrandService


def test_hard_facts_and_missing_fallbacks():
    print("--- 1. Testing Hard Facts & Missing Fallback Protection ---")
    
    # Случай A: Текст БЕЗ цен и БЕЗ сроков (типичный лендинг с красивыми словами)
    empty_hard_facts_text = """
    Мы — премиальная кофейня 'Coffee Loft' в центре Москвы. У нас уютная атмосфера,
    красивый дизайн, авторские напитки и вкуснейшие десерты. Ждем вас каждый день!
    Телефон: +7 (999) 111-22-33.
    """
    dossier_a = NichePriorsEngine.build_tiered_dossier(
        raw_text=empty_hard_facts_text,
        company_name="Coffee Loft",
        niche="кофейня"
    )

    # Проверка: цены и гарантии НЕ должны быть выдуманы!
    pricing_a = dossier_a.hard_facts.get("pricing_model")
    assert pricing_a is not None, "pricing_model must be in hard_facts"
    assert pricing_a.source == FieldProvenanceEnum.MISSING, f"Expected MISSING pricing, got {pricing_a.source}"
    assert pricing_a.confidence == 0.0, f"Expected 0.0 confidence, got {pricing_a.confidence}"
    assert pricing_a.value is None, f"Expected None value for missing price, got {pricing_a.value}"
    assert pricing_a.fallback_strategy in [FallbackStrategyEnum.CTA_TO_DM, FallbackStrategyEnum.PRICE_ON_REQUEST]
    assert "pricing_model" in dossier_a.missing_hard_slots

    terms_a = dossier_a.hard_facts.get("terms_guarantees")
    assert terms_a.source == FieldProvenanceEnum.MISSING
    assert terms_a.fallback_strategy == FallbackStrategyEnum.CTA_TO_DM

    # Телефон извлечен как подтвержденный факт
    phones_a = dossier_a.hard_facts.get("phones")
    assert phones_a is not None
    assert phones_a.source == FieldProvenanceEnum.EXTRACTED
    assert phones_a.confidence == 1.0

    print("   ✅ Случай A (Нет цен): цены помечены MISSING, confidence 0.0, назначен CTA_TO_DM.")

    # Случай B: Текст С точными ценами и сроками
    rich_hard_facts_text = """
    Кофейня 'Coffee Roasters'.
    Эспрессо — 180 руб, капучино — 280 руб, авторский раф — 350 руб.
    Доставка зерен за 24 часа по Москве. Гарантия свежести обжарки 30 дней.
    """
    dossier_b = NichePriorsEngine.build_tiered_dossier(
        raw_text=rich_hard_facts_text,
        company_name="Coffee Roasters",
        niche="кофейня"
    )

    pricing_b = dossier_b.hard_facts.get("pricing_model")
    assert pricing_b.source == FieldProvenanceEnum.EXTRACTED, f"Expected EXTRACTED, got {pricing_b.source}"
    assert pricing_b.confidence == 1.0
    assert len(pricing_b.value) > 0
    assert "pricing_model" not in dossier_b.missing_hard_slots

    terms_b = dossier_b.hard_facts.get("terms_guarantees")
    assert terms_b.source == FieldProvenanceEnum.EXTRACTED
    assert terms_b.confidence == 1.0

    print("   ✅ Случай B (С ценами): цены и сроки извлечены как EXTRACTED, confidence 1.0.")
    print("SUCCESS: test_hard_facts_and_missing_fallbacks passed!\n")


def test_soft_attributes_and_niche_priors():
    print("--- 2. Testing Soft Attributes & Niche Priors Inference ---")
    
    text = "Юридическая компания 'Право и Закон'. Профессиональные услуги для корпоративных клиентов."
    dossier = NichePriorsEngine.build_tiered_dossier(
        raw_text=text,
        company_name="Право и Закон",
        niche="b2b юрист консалтинг"
    )

    # 1. Тон коммуникации автодополнен по нише B2B
    tov = dossier.soft_attributes.get("tone_of_voice")
    assert tov is not None
    assert tov.source == FieldProvenanceEnum.INFERRED_NICHE_PRIOR
    assert tov.is_inferred is True
    assert tov.confidence == 0.85
    assert "Строгий" in tov.value or "аналитический" in tov.value

    # 2. Боли аудитории автодополнены по нише B2B
    pains = dossier.soft_attributes.get("pain_points")
    assert pains is not None
    assert pains.source == FieldProvenanceEnum.INFERRED_NICHE_PRIOR
    assert pains.is_inferred is True
    assert len(pains.value) >= 3
    print(f"   Inferred B2B Pains: {pains.value[:2]}")

    # 3. Визуальные пропсы автодополнены по онтологии
    props = dossier.soft_attributes.get("visual_props")
    assert props is not None
    assert len(props.value) >= 2

    # 4. Anti-Hallucination Guardrails
    guardrails = dossier.get_anti_hallucination_guardrails()
    assert "ЗАПРЕЩЕНО выдумывать рубли" in guardrails
    assert "ТОН ОБЩЕНИЯ" in guardrails.upper()
    print("   Generated Guardrails snippet:\n   " + "\n   ".join(guardrails.split("\n")[:4]))

    print("SUCCESS: test_soft_attributes_and_niche_priors passed!\n")


def test_dynamic_attributes_extraction():
    print("--- 3. Testing Dynamic / Unknown Fields (Dynamic JSONB) ---")
    
    specialty_coffee_text = """
    Наш флагман — Эфиопия Иргачефф.
    Степень обжарки: светлая городская обжарка для фильтра.
    Высота произрастания: 2100 метров над уровнем моря.
    Вкусовые ноты: жасмин, бергамот, спелый персик.
    """
    dossier = NichePriorsEngine.build_tiered_dossier(
        raw_text=specialty_coffee_text,
        company_name="Specialty Hub",
        niche="кофейня"
    )

    # Динамические поля: 'dyn_обжарка', 'dyn_высота', 'dyn_ноты'
    assert len(dossier.dynamic_attributes) > 0, "Expected dynamic attributes to be extracted"
    for k, field in dossier.dynamic_attributes.items():
        assert field.category == FieldCategoryEnum.DYNAMIC_FIELD
        assert field.source == FieldProvenanceEnum.EXTRACTED
        print(f"   Extracted Dynamic Slot '{k}': {field.value[:60]}...")

    print("SUCCESS: test_dynamic_attributes_extraction passed!\n")


async def test_document_collector_and_brand_service_integration():
    print("--- 4. Testing DocumentCollector & BrandService Integration ---")

    # Имитируем загрузку документа клиента
    mock_doc = {
        "file_name": "commercial_offer.txt",
        "format": "txt",
        "status": "success",
        "raw_text": (
            "Коммерческое предложение компании 'ТехноСнаб' (B2B поставки).\n"
            "Стоимость оптовой партии: от 250 000 руб со скидкой 10%.\n"
            "Срок отгрузки со склада: в течение 3 рабочих дней.\n"
            "Телефон отдела продаж: +7 495 777-88-99. Email: b2b@technosnab.ru.\n"
            "Лицензия СРО №12345-МСК. Соответствие ГОСТ 52544-2006."
        )
    }

    collector = DocumentCollector()
    tiered_dossier = collector.synthesize_tiered_dossier(
        extracted_docs=[mock_doc],
        company_name="ТехноСнаб",
        niche="b2b оптовые поставки"
    )

    assert tiered_dossier.company_name == "ТехноСнаб"
    assert "pricing_model" in tiered_dossier.hard_facts
    assert tiered_dossier.hard_facts["pricing_model"].source == FieldProvenanceEnum.EXTRACTED
    assert "terms_guarantees" in tiered_dossier.hard_facts
    assert tiered_dossier.hard_facts["terms_guarantees"].source == FieldProvenanceEnum.EXTRACTED

    # Проверка RAG-разметки фактов
    verified_facts = [f for f in tiered_dossier.rag_grounded_facts if f.startswith("[VERIFIED]")]
    prior_facts = [f for f in tiered_dossier.rag_grounded_facts if f.startswith("[NICHE_PRIOR]")]
    assert len(verified_facts) >= 2, f"Expected verified facts, got {verified_facts}"
    assert len(prior_facts) >= 2, f"Expected prior facts, got {prior_facts}"

    # Проверяем BrandService.extract_documents
    class MockRAG:
        async def ingest_documents_async(self, docs):
            for d in docs:
                assert "trust_tier" in d.metadata, f"Missing trust_tier in doc {d.doc_id}"
                assert "source" in d.metadata, f"Missing source in doc {d.doc_id}"
                assert "is_synthetic" in d.metadata, f"Missing is_synthetic in doc {d.doc_id}"
            return len(docs)

    brand_service = BrandService(rag_pipeline=MockRAG())
    # Тестовый файл
    test_file_path = "test_commercial_doc.txt"
    with open(test_file_path, "w", encoding="utf-8") as f:
        f.write(mock_doc["raw_text"])

    try:
        res = await brand_service.extract_documents(
            file_paths=[test_file_path],
            company_name="ТехноСнаб",
            niche="b2b оптовые поставки"
        )
        assert res["status"] == "success"
        assert res["extracted_count"] == 1
        assert res["indexed_count"] > 0
        assert "tiered_dossier" in res
        assert "anti_hallucination_guardrails" in res
        assert "prefilled_profile" in res
        print(f"   Indexed RAG chunks & facts count: {res['indexed_count']}")
        print(f"   Data Richness Score: {res['data_richness_score']}/100 (Tier: {res['drs_tier']})")
    finally:
        if os.path.exists(test_file_path):
            os.remove(test_file_path)

    print("SUCCESS: test_document_collector_and_brand_service_integration passed!\n")


if __name__ == "__main__":
    test_hard_facts_and_missing_fallbacks()
    test_soft_attributes_and_niche_priors()
    test_dynamic_attributes_extraction()
    asyncio.run(test_document_collector_and_brand_service_integration())
    print("🎉 ALL METADATA PROVENANCE & TIERED SLOT FILLING TESTS PASSED!")

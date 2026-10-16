"""
File: ai/scripts/test_stratified_rag_layers.py
Интеграционный тест 4-слойной архитектуры знаний Clean RAG:
1. Multi-Tenant Pre-Filtering: 100% изоляция данных между клиентами (исключение Cross-Client Bleed).
2. Metadata Layer Pre-Filtering: жесткое разграничение по doc_category (hard_fact, brand_dna, audience_priors, episodic_memory).
3. Platform Targeting: фильтрация platform_target (all, telegram, vk, ok) с корректным включением универсальных чанков.
4. query_stratified_context_async: параллельная сборка сбалансированного 4-слойного контекста с защитой от галлюцинаций.
"""

import sys
import os
import asyncio
from typing import List, Dict, Any

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rag.models import (
    Document,
    DocCategoryEnum,
    TrustTierEnum,
    PlatformTargetEnum,
    RAGContext
)
from rag.pipeline import CleanRAGPipeline


def setup_test_pipeline() -> CleanRAGPipeline:
    rag = CleanRAGPipeline(
        target_chunk_tokens=300,
        overlap_tokens=30,
        min_confidence_threshold=0.30  # для тестирования разных рангов
    )
    return rag


def populate_test_data(rag: CleanRAGPipeline):
    """Индексация данных для двух разных тенантов и 4 слоев знаний."""
    # ── Tenant 1: Bakery Sweet (Пекарня) ───────────────────────────────────
    bakery_docs = [
        # Слой 1: Hard Ground Truth (Жёсткие факты)
        Document(
            doc_id="bakery_fact_1",
            text="Кулич пасхальный фирменный. Вес: 500г. Цена: 1230 руб. Состав: фермерское сливочное масло 82.5%, цукаты апельсина, натуральная ваниль, 72 часа бережной ферментации. Промокод: ПАСХА2026 дает скидку 10%.",
            metadata={
                "tenant_id": "bakery_sweet",
                "client_id": "bakery_sweet",
                "doc_category": DocCategoryEnum.HARD_FACT.value,
                "trust_tier": TrustTierEnum.VERIFIED_BY_OWNER.value,
                "platform_target": PlatformTargetEnum.ALL.value,
                "category": "hard_fact"
            },
            source="owner_pricelist"
        ),
        # Слой 2: Brand DNA & Tone of Voice
        Document(
            doc_id="bakery_dna_1",
            text="Редполитика и ToV: Теплый, дружелюбный, ремесленный тон семейной пекарни. Без официоза. Эмодзи не более 2 в посте. Антипример: ❌ 'Мы динамично развивающаяся компания' -> ✅ 'Печем ремесленный хлеб и пасхальные куличи с 2018 года'.",
            metadata={
                "tenant_id": "bakery_sweet",
                "client_id": "bakery_sweet",
                "doc_category": DocCategoryEnum.BRAND_DNA.value,
                "trust_tier": TrustTierEnum.VERIFIED_BY_OWNER.value,
                "platform_target": PlatformTargetEnum.ALL.value,
                "category": "brand_dna"
            },
            source="brand_dna_guide"
        ),
        # Слой 3: Audience Priors & Context
        Document(
            doc_id="bakery_priors_1",
            text="Боли аудитории: надоели сухие заводские куличи с осыпающейся химической глазурью; страх получить черствый продукт к празднику. Главный триггер: мягкий влажный мякиш, который тает во рту и сохраняет свежесть 7 дней.",
            metadata={
                "tenant_id": "bakery_sweet",
                "client_id": "bakery_sweet",
                "doc_category": DocCategoryEnum.AUDIENCE_PRIORS.value,
                "trust_tier": TrustTierEnum.INFERRED_NICHE.value,
                "platform_target": PlatformTargetEnum.ALL.value,
                "category": "audience_priors"
            },
            source="niche_audience_analysis"
        ),
        # Слой 4: Episodic Memory (Директивы владельца)
        Document(
            doc_id="bakery_memory_1",
            text="[2026-10-15 Директива владельца]: Слово 'уникальный' строго запрещено во всех постах и сторис! В анонсах Пасхи обязательно подчеркивать 72 часа ферментации теста.",
            metadata={
                "tenant_id": "bakery_sweet",
                "client_id": "bakery_sweet",
                "doc_category": DocCategoryEnum.EPISODIC_MEMORY.value,
                "trust_tier": TrustTierEnum.SYSTEM_DIRECTIVE.value,
                "platform_target": PlatformTargetEnum.ALL.value,
                "category": "episodic_memory"
            },
            source="moderator_feedback_log"
        ),
        # Платформо-специфичные посты
        Document(
            doc_id="bakery_tg_post",
            text="Эксклюзивно для подписчиков Telegram-канала: секретный промокод TELEGA_SWEET на бесплатную чашку кофе к любому куличу.",
            metadata={
                "tenant_id": "bakery_sweet",
                "client_id": "bakery_sweet",
                "doc_category": DocCategoryEnum.BRAND_DNA.value,
                "trust_tier": TrustTierEnum.VERIFIED_BY_OWNER.value,
                "platform_target": PlatformTargetEnum.TELEGRAM.value,
            },
            source="tg_channel_posts"
        ),
        Document(
            doc_id="bakery_vk_post",
            text="ВКонтакте: участвуйте в праздничном конкурсе репостов и выиграйте корзину выпечки для всей семьи!",
            metadata={
                "tenant_id": "bakery_sweet",
                "client_id": "bakery_sweet",
                "doc_category": DocCategoryEnum.BRAND_DNA.value,
                "trust_tier": TrustTierEnum.VERIFIED_BY_OWNER.value,
                "platform_target": PlatformTargetEnum.VK.value,
            },
            source="vk_community_posts"
        ),
    ]

    # ── Tenant 2: Drift Racing Club (Автоспорт) ───────────────────────────
    racing_docs = [
        Document(
            doc_id="racing_fact_1",
            text="Билет на трибуну Russian Drift Series (RDS). Стоимость: 3500 руб. Включает проход в закрытый техпарк, автограф-сессию с пилотами и доступ на питлейн. Старт заездов в 12:00.",
            metadata={
                "tenant_id": "drift_racing",
                "client_id": "drift_racing",
                "doc_category": DocCategoryEnum.HARD_FACT.value,
                "trust_tier": TrustTierEnum.VERIFIED_BY_OWNER.value,
                "platform_target": PlatformTargetEnum.ALL.value,
            },
            source="rds_ticket_office"
        ),
        Document(
            doc_id="racing_dna_1",
            text="ToV: Драйвовый, дерзкий, адреналиновый стиль. Слова-триггеры: дым из-под колес, угол заноса, перекладка, отсечка, 800+ л.с.",
            metadata={
                "tenant_id": "drift_racing",
                "client_id": "drift_racing",
                "doc_category": DocCategoryEnum.BRAND_DNA.value,
                "trust_tier": TrustTierEnum.VERIFIED_BY_OWNER.value,
                "platform_target": PlatformTargetEnum.ALL.value,
            },
            source="racing_brand_book"
        ),
    ]

    rag.ingest_documents(bakery_docs + racing_docs)


def test_tenant_isolation_and_prefiltering(rag: CleanRAGPipeline):
    print("--- 1. Testing Strict Tenant Isolation (Zero Cross-Client Bleed) ---")

    # Запрос от лица Bakery Sweet по поводу билетов и дрифта:
    # В базе Bakery НЕТ данных о RDS билетах! Никакие данные drift_racing не должны утечь!
    res_bakery = rag.query("Сколько стоит билет на RDS трибуну?", tenant_id="bakery_sweet")
    for chunk in res_bakery.chunks:
        assert chunk.metadata.get("tenant_id") == "bakery_sweet", f"Cross-tenant leak detected: {chunk.metadata}"
        assert "3500" not in chunk.text, f"Price leaked from another tenant: {chunk.text}"

    # Запрос от лица Drift Racing по поводу кулича:
    res_racing = rag.query("Сколько стоит пасхальный кулич?", tenant_id="drift_racing")
    for chunk in res_racing.chunks:
        assert chunk.metadata.get("tenant_id") == "drift_racing", f"Cross-tenant leak detected: {chunk.metadata}"
        assert "1230" not in chunk.text, f"Bakery price leaked into racing: {chunk.text}"

    # Прямой легитимный запрос каждого тенанта
    res_valid_bakery = rag.query("пасхальный кулич цена состав", tenant_id="bakery_sweet")
    assert res_valid_bakery.has_sufficient_context is True
    assert any("1230 руб" in c.text for c in res_valid_bakery.chunks)

    res_valid_racing = rag.query("билет на трибуну RDS цена", tenant_id="drift_racing")
    assert res_valid_racing.has_sufficient_context is True
    assert any("3500 руб" in c.text for c in res_valid_racing.chunks)

    print("   ✅ Strict Multi-Tenant isolation verified: 0% data leakage between clients.\n")


def test_metadata_layer_prefiltering(rag: CleanRAGPipeline):
    print("--- 2. Testing Metadata Pre-Filtering by doc_category ---")

    # 1. Запрос только к Hard Facts (цены, составы)
    res_facts = rag.query(
        "кулич редполитика боли",
        tenant_id="bakery_sweet",
        filters={"doc_category": DocCategoryEnum.HARD_FACT.value}
    )
    assert len(res_facts.chunks) > 0
    for chunk in res_facts.chunks:
        cat = chunk.metadata.get("doc_category") or chunk.metadata.get("category")
        assert cat == DocCategoryEnum.HARD_FACT.value, f"Expected hard_fact, got {cat}"

    # 2. Запрос только к Brand DNA
    res_dna = rag.query(
        "кулич редполитика тон",
        tenant_id="bakery_sweet",
        filters={"doc_category": DocCategoryEnum.BRAND_DNA.value}
    )
    assert len(res_dna.chunks) > 0
    for chunk in res_dna.chunks:
        cat = chunk.metadata.get("doc_category") or chunk.metadata.get("category")
        assert cat == DocCategoryEnum.BRAND_DNA.value, f"Expected brand_dna, got {cat}"

    # 3. Запрос только к Episodic Memory (директивы)
    res_memory = rag.query(
        "директива слово уникальный запрещено",
        tenant_id="bakery_sweet",
        filters={"doc_category": DocCategoryEnum.EPISODIC_MEMORY.value}
    )
    assert len(res_memory.chunks) > 0
    for chunk in res_memory.chunks:
        cat = chunk.metadata.get("doc_category") or chunk.metadata.get("category")
        assert cat == DocCategoryEnum.EPISODIC_MEMORY.value, f"Expected episodic_memory, got {cat}"

    print("   ✅ Layer Pre-Filtering verified: Each layer query retrieves exclusively its category.\n")


def test_platform_targeting(rag: CleanRAGPipeline):
    print("--- 3. Testing Platform Target Pre-Filtering ---")

    # Запрос для Telegram: должен вернуть Telegram-чанги + Универсальные (all), но НЕ VK
    res_tg = rag.query(
        "промокод конкурс розыгрыш",
        tenant_id="bakery_sweet",
        filters={"platform_target": "telegram"}
    )
    assert len(res_tg.chunks) > 0
    for c in res_tg.chunks:
        plt = c.metadata.get("platform_target")
        assert plt in {"telegram", "all"}, f"Unexpected platform in TG query: {plt}"
        assert "ВКонтакте" not in c.text, "VK-only content leaked into Telegram search!"

    # Запрос для VK: должен вернуть VK-чанги + Универсальные (all), но НЕ Telegram
    res_vk = rag.query(
        "промокод конкурс розыгрыш",
        tenant_id="bakery_sweet",
        filters={"platform_target": "vk"}
    )
    assert len(res_vk.chunks) > 0
    for c in res_vk.chunks:
        plt = c.metadata.get("platform_target")
        assert plt in {"vk", "all"}, f"Unexpected platform in VK query: {plt}"
        assert "TELEGA_SWEET" not in c.text, "Telegram-only content leaked into VK search!"

    print("   ✅ Platform Targeting verified: TG and VK platform-specific posts properly partitioned.\n")


async def test_stratified_context_query(rag: CleanRAGPipeline):
    print("--- 4. Testing query_stratified_context_async ---")

    ctx: RAGContext = await rag.query_stratified_context_async(
        query_text="Расскажи про пасхальный кулич, цену, как писать пост и какие боли у клиентов",
        tenant_id="bakery_sweet",
        platform_target="telegram",
        per_layer_k=2
    )

    assert ctx.has_sufficient_context is True
    assert ctx.stratified_layers is not None

    # Проверяем наполнение слоёв
    hard_chunks = ctx.get_layer(DocCategoryEnum.HARD_FACT.value)
    dna_chunks = ctx.get_layer(DocCategoryEnum.BRAND_DNA.value)
    priors_chunks = ctx.get_layer(DocCategoryEnum.AUDIENCE_PRIORS.value)
    memory_chunks = ctx.get_layer(DocCategoryEnum.EPISODIC_MEMORY.value)

    assert len(hard_chunks) > 0, "Hard facts layer must contain chunks"
    assert len(dna_chunks) > 0, "Brand DNA layer must contain chunks"
    assert len(priors_chunks) > 0, "Audience priors layer must contain chunks"
    assert len(memory_chunks) > 0, "Episodic memory layer must contain chunks"

    assert ctx.has_hard_facts is True

    # Проверяем форматированный контекст
    fmt = ctx.formatted_context
    assert "=== СЛОЙ 1: HARD GROUND TRUTH" in fmt
    assert "=== СЛОЙ 2: BRAND DNA & REDPOLICY" in fmt
    assert "=== СЛОЙ 3: AUDIENCE PRIORS" in fmt
    assert "=== СЛОЙ 4: EPISODIC MEMORY" in fmt
    assert "1230 руб" in fmt
    assert "Слово 'уникальный' строго запрещено" in fmt

    print("   ✅ Formatted Stratified Context successfully generated with all 4 layers.")
    print("   ✅ Top score:", ctx.top_score)
    print("   ✅ Total chunks in stratified context:", len(ctx.chunks))
    print("\n   [Snippet of Formatted Stratified Context]:")
    for line in fmt.split("\n")[:18]:
        print(f"      {line}")
    print("      ...\n")


def main():
    print("🚀 STARTING 4-LAYER STRATIFIED RAG & PRE-FILTERING INTEGRATION TESTS\n")
    rag = setup_test_pipeline()
    populate_test_data(rag)

    test_tenant_isolation_and_prefiltering(rag)
    test_metadata_layer_prefiltering(rag)
    test_platform_targeting(rag)
    asyncio.run(test_stratified_context_query(rag))

    print("🎉 ALL 4-LAYER STRATIFIED RAG & PRE-FILTERING TESTS PASSED 100%!")


if __name__ == "__main__":
    main()

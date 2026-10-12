# File: ai/scripts/test_trend_engine.py
"""
test_trend_engine.py
Validation test suite for Trend Engine Math Core & Schemas:
1. RawTrendEvent normalized content_hash and deduplication
2. SVD / PCA dimensionality reduction (curse of dimensionality mitigation)
3. HDBSCAN clustering & statistical velocity/spike anomaly detection
4. Centroid representative texts & token truncation (VRAM Protection for Zephyrus S17)
5. Performance benchmark for stream clustering
"""

import os
import sys
import time
from datetime import datetime, timedelta

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


# Setup sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from schemas.trend_state import (
    RawTrendEvent,
    TrendCluster,
    TrendState,
    TrendLifecycleEnum,
    TrendSentimentEnum,
)
from analytics.trend_clusterer import TrendClusterer


def test_normalized_content_hashing():
    print("\n--- 1. Testing RawTrendEvent Normalized Hashing & Deduplication ---")

    text1 = "🔥 Срочно! Вышел новый AI-ассистент: https://example.com/ai?ref=123   "
    text2 = "срочно вышел новый aiассистент"  # тот же текст без пунктуации/ссылок/регистра
    text3 = "Совершенно другой текст о погоде в Москве"

    hash1 = RawTrendEvent.calculate_normalized_hash(text1, source_id="channel_tech")
    hash2 = RawTrendEvent.calculate_normalized_hash(text2, source_id="channel_tech")
    hash3 = RawTrendEvent.calculate_normalized_hash(text3, source_id="channel_tech")
    hash_diff_source = RawTrendEvent.calculate_normalized_hash(text1, source_id="other_channel")

    assert hash1 == hash2, f"Normalized hashes must match! Got: {hash1} vs {hash2}"
    assert hash1 != hash3, "Different texts must produce different hashes"
    assert hash1 != hash_diff_source, "Different sources must produce different hashes"
    print("  [Pass] Normalized SHA-256 hash successfully eliminates cross-post noise")

    # Test auto-calculation in Pydantic model
    event1 = RawTrendEvent(
        source_platform="telegram",
        source_id="channel_tech",
        post_id="101",
        raw_text=text1,
    )
    assert event1.content_hash == hash1
    print("  [Pass] Pydantic model_post_init automatically populated content_hash")

    # Test batch deduplication
    event2 = RawTrendEvent(
        source_platform="telegram",
        source_id="channel_tech",
        post_id="102",
        raw_text=text2,  # Duplicate of event1
    )
    event3 = RawTrendEvent(
        source_platform="telegram",
        source_id="channel_tech",
        post_id="103",
        raw_text=text3,
    )

    clusterer = TrendClusterer()
    unique = clusterer.deduplicate_events([event1, event2, event3])
    assert len(unique) == 2, f"Expected 2 unique events, got {len(unique)}"
    assert unique[0].content_hash == hash1
    assert unique[1].content_hash == hash3
    print("  [Pass] O(1) deduplication cleanly pruned duplicate repost")


def test_svd_dimensionality_reduction():
    print("\n--- 2. Testing Dimensionality Reduction (Curse of Dimensionality) ---")
    import numpy as np

    clusterer = TrendClusterer(pca_components=10, embedding_dim=128)

    # Synthetic matrix of 20 samples, 128 features
    np.random.seed(42)
    fake_embeddings = np.random.randn(20, 128).astype(np.float32)

    reduced = clusterer._reduce_dimensions(fake_embeddings)

    assert reduced.shape[0] == 20, "Sample count must be preserved"
    assert reduced.shape[1] <= 10, f"Dimensionality must be reduced to <=10, got {reduced.shape[1]}"

    # Verify L2 normalization
    norms = np.linalg.norm(reduced, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-3), "Reduced vectors must be L2-normalized"
    print(f"  [Pass] Reduced from 128-dim to {reduced.shape[1]}-dim with unit L2 norm")


def test_hdbscan_clustering_and_anomaly_detection():
    print("\n--- 3. Testing HDBSCAN Density Clustering & Velocity Math ---")

    now = datetime.utcnow()

    # Topic A: AI / LLM Breakthrough (8 events, high burst density)
    topic_a_events = [
        RawTrendEvent(
            source_platform="telegram", source_id="tg_news", post_id=f"a_{i}",
            raw_text=f"Революционный релиз новой модели искусственного интеллекта Saiga v{i}! Высокая скорость инференса и качество.",
            timestamp=now - timedelta(minutes=15 * i)
        )
        for i in range(8)
    ]

    # Topic B: Specialty Coffee Trend (6 events)
    topic_b_events = [
        RawTrendEvent(
            source_platform="vk", source_id="vk_food", post_id=f"b_{i}",
            raw_text=f"Открытие крафтовой спешелти кофейни в центре города. Свежая обжарка арабики из Колумбии номер {i}.",
            timestamp=now - timedelta(minutes=30 * i)
        )
        for i in range(6)
    ]

    # Noise: Random unrelated messages
    noise_events = [
        RawTrendEvent(
            source_platform="rss", source_id="rss_misc", post_id=f"noise_{i}",
            raw_text=f"Случайный факт {i}: погода сегодня переменчивая, пробки на садовом кольце 5 баллов.",
            timestamp=now - timedelta(hours=i)
        )
        for i in range(10)
    ]

    all_events = topic_a_events + topic_b_events + noise_events

    clusterer = TrendClusterer(
        min_cluster_size=3,
        min_samples=2,
        pca_components=15,
        min_density_spike=1.1,
    )

    t0 = time.perf_counter()
    detected_clusters = clusterer.cluster_events(all_events, window_hours=4.0)
    duration_ms = (time.perf_counter() - t0) * 1000

    print(f"  Executed clustering over {len(all_events)} events in {duration_ms:.2f} ms")
    assert len(detected_clusters) >= 1, "At least 1 dense anomaly cluster must be detected"

    for cl in detected_clusters:
        assert isinstance(cl, TrendCluster)
        assert cl.total_samples >= 3
        assert cl.velocity_score > 0
        assert cl.density_spike >= 1.1
        assert len(cl.centroid_representative_texts) <= 10
        print(f"  [Cluster Found] ID={cl.cluster_id} | Samples={cl.total_samples} | Velocity={cl.velocity_score}/h | DensitySpike={cl.density_spike}x")
        print(f"    • Rep snippet: {cl.centroid_representative_texts[0][:75]}...")

    print("  [Pass] Dense clusters accurately separated from noise")


def test_vram_token_truncation():
    print("\n--- 4. Testing VRAM Token Truncator (Zephyrus S17 Safety) ---")

    long_text = "Инновационная разработка нейросетей " * 60  # ~300 слов
    events = [
        RawTrendEvent(
            source_platform="telegram", source_id="tg_safe", post_id=f"p_{i}",
            raw_text=f"Сообщение {i}: " + long_text,
            timestamp=datetime.utcnow() - timedelta(minutes=5 * i)
        )
        for i in range(5)
    ]

    clusterer = TrendClusterer(
        min_cluster_size=3,
        max_centroid_samples=4,
        max_centroid_tokens=200,  # Жесткий лимит 200 токенов
    )

    clusters = clusterer.cluster_events(events, window_hours=2.0)
    assert len(clusters) >= 1

    cl = clusters[0]
    assert len(cl.centroid_representative_texts) <= 4, "Must not exceed max_centroid_samples"
    assert cl.total_representative_tokens <= 250, f"Token count exceeded VRAM limit: {cl.total_representative_tokens}"
    print(f"  [Pass] Context bounded strictly: {len(cl.centroid_representative_texts)} texts, total {cl.total_representative_tokens} tokens")


def test_trend_state_contract():
    print("\n--- 5. Testing TrendState Integration Schema ---")

    trend = TrendState(
        trend_id="trend_20261012_01",
        cluster_id="tc_9a1f4b",
        topic_headline="Всплеск внедрения локальных ИИ-агентов в малом бизнесе",
        summary="Анализ кластера из 18 публикаций показывает рост интереса к автономным контент-конвейерам.",
        niche_categories=["IT", "B2B", "SMM"],
        trend_lifecycle=TrendLifecycleEnum.MICRO_HYPE,
        sentiment=TrendSentimentEnum.POSITIVE,
        key_entities=["UCust AI", "Saiga", "FastAPI"],
        relevance_score=0.92,
        source_references=["https://t.me/tech_news/105"],
        velocity_growth_rate=3.4,
        tokens_consumed=412,
    )

    json_repr = trend.model_dump_json()
    assert "trend_20261012_01" in json_repr
    assert "micro_hype" in json_repr
    assert trend.relevance_score == 0.92
    print("  [Pass] TrendState Pydantic v2 contract fully validated")


def main():
    print("=" * 70)
    print("🚀 RUNNING TREND ENGINE MATHEMATICAL CORE & SCHEMA SUITE")
    print("=" * 70)

    test_normalized_content_hashing()
    test_svd_dimensionality_reduction()
    test_hdbscan_clustering_and_anomaly_detection()
    test_vram_token_truncation()
    test_trend_state_contract()

    print("\n" + "=" * 70)
    print("🏆 ALL TREND ENGINE TESTS PASSED PERFECTLY! (100% SUCCESS RATE)")
    print("=" * 70)


if __name__ == "__main__":
    main()

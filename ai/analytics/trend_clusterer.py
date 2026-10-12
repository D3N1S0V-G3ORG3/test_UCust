"""
File: ai/analytics/trend_clusterer.py
Модуль математической кластеризации и детекции аномалий Trend Engine.
Реализует:
1. Защиту от проклятия размерности (Dimensionality Reduction via TruncatedSVD / PCA).
2. Плотную кластеризацию потоковых данных (HDBSCAN / DBSCAN).
3. Расчет скорости нарастания (velocity_score) и всплеска плотности (density_spike).
4. Центроидную выборку и жесткую токеновую транкацию (VRAM Protection для Zephyrus S17).
"""

from __future__ import annotations

import math
import re
import uuid
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple, Set
import numpy as np

from schemas.trend_state import RawTrendEvent, TrendCluster

logger = logging.getLogger("TrendClusterer")

try:
    from sklearn.cluster import HDBSCAN, DBSCAN
    from sklearn.decomposition import TruncatedSVD
    from sklearn.preprocessing import normalize
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


class TrendClusterer:
    """
    Математическое ядро детекции трендов:
    - Дедуплицирует сырые события по content_hash.
    - Векторизует очищенные тексты (Dense Embeddings).
    - Выполняет проекцию в подпространство низкой размерности (Curse of Dimensionality mitigation).
    - Выявляет статистически аномальные плотностные сгустки (HDBSCAN).
    - Формирует контракты TrendCluster с усеченным контекстом центроида.
    """

    def __init__(
        self,
        min_cluster_size: int = 3,
        min_samples: int = 2,
        pca_components: int = 20,
        max_centroid_samples: int = 7,
        max_centroid_tokens: int = 1200,
        min_density_spike: float = 1.3,
        embedding_dim: int = 384,
    ):
        self.min_cluster_size = min_cluster_size
        self.min_samples = min_samples
        self.pca_components = pca_components
        self.max_centroid_samples = min(10, max_centroid_samples)
        self.max_centroid_tokens = max_centroid_tokens
        self.min_density_spike = min_density_spike
        self.embedding_dim = embedding_dim

        # Опциональная модель эмбеддингов
        self._embedding_model = None
        self._init_embedding_model()

    def _init_embedding_model(self):
        try:
            from sentence_transformers import SentenceTransformer
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._embedding_model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2", device=device)
            logger.info(f"[TrendClusterer] 🧠 Загружен SentenceTransformer (device={device})")
        except Exception:
            self._embedding_model = None

    def _approximate_token_count(self, text: str) -> int:
        """Оценка количества токенов (русский/английский текст) без блокировки GPU."""
        if not text:
            return 0
        # В среднем для кириллицы BPE токенизатор дает ~1 токен на 3 символа
        return max(1, len(text) // 3)

    def deduplicate_events(self, events: List[RawTrendEvent]) -> List[RawTrendEvent]:
        """
        O(1) дедупликация событий по криптографическому content_hash.
        Отсекает точные и нормализованные репосты до векторизации.
        """
        seen_hashes: Set[str] = set()
        unique_events: List[RawTrendEvent] = []
        for ev in events:
            h = ev.content_hash or RawTrendEvent.calculate_normalized_hash(ev.raw_text, ev.source_id)
            if h not in seen_hashes:
                seen_hashes.add(h)
                unique_events.append(ev)
        logger.info(f"[TrendClusterer] 🔍 Дедупликация: {len(events)} -> {len(unique_events)} уникальных событий.")
        return unique_events

    def _vectorize_texts(self, texts: List[str]) -> np.ndarray:
        """Векторизация текстов с fallback на TF-IDF / Cosine Bag."""
        if not texts:
            return np.empty((0, self.embedding_dim))

        if self._embedding_model is not None:
            try:
                embeddings = self._embedding_model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
                return np.array(embeddings, dtype=np.float32)
            except Exception as e:
                logger.warning(f"[TrendClusterer] Ошибка SentenceTransformer: {e}. Применен быстрый fallback.")

        # Высокоскоростной векторный fallback
        vectors = np.zeros((len(texts), self.embedding_dim), dtype=np.float32)
        for i, text in enumerate(texts):
            words = re.findall(r"\w+", text.lower())
            if not words:
                continue
            for w in words:
                idx = abs(hash(w)) % self.embedding_dim
                vectors[i, idx] += 1.0
            norm = np.linalg.norm(vectors[i])
            if norm > 0:
                vectors[i] /= norm
        return vectors

    def _reduce_dimensions(self, embeddings: np.ndarray) -> np.ndarray:
        """
        Снижение размерности (Curse of Dimensionality mitigation) через TruncatedSVD.
        Предотвращает эффект схлопывания расстояний в HDBSCAN.
        """
        n_samples, n_features = embeddings.shape
        if n_samples <= 3 or not HAS_SKLEARN:
            return embeddings

        # Число компонент не должно превышать число сэмплов и признаков
        target_components = min(self.pca_components, n_samples - 1, n_features - 1)
        if target_components < 2:
            return embeddings

        try:
            svd = TruncatedSVD(n_components=target_components, random_state=42)
            reduced = svd.fit_transform(embeddings)
            # L2-нормализация для сохранения угловых/косинусных расстояний в евклидовом пространстве
            return normalize(reduced, norm="l2")
        except Exception as e:
            logger.warning(f"[TrendClusterer] Ошибка TruncatedSVD: {e}. Используем исходные векторы.")
            return embeddings

    def _extract_centroid_texts(
        self,
        cluster_indices: List[int],
        events: List[RawTrendEvent],
        embeddings: np.ndarray
    ) -> Tuple[List[str], int, List[float]]:
        """
        Находит центроид кластера и отбирает топ-N наиболее репрезентативных текстов,
        применяя жесткое усечение токенов (Zephyrus S17 VRAM Protection).
        """
        sub_vectors = embeddings[cluster_indices]
        centroid = np.mean(sub_vectors, axis=0)
        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid /= norm

        # Считаем косинусное сходство каждой точки с центроидом
        sims = np.dot(sub_vectors, centroid)
        ranked_local_indices = np.argsort(-sims)

        selected_texts: List[str] = []
        accumulated_tokens = 0

        for local_idx in ranked_local_indices:
            if len(selected_texts) >= self.max_centroid_samples:
                break
            global_idx = cluster_indices[local_idx]
            text = events[global_idx].raw_text.strip()
            text_tokens = self._approximate_token_count(text)

            # Если один текст слишком длинный — усекаем его до 250 токенов (~750 символов)
            if text_tokens > 250:
                text = text[:750].rsplit(" ", 1)[0] + "..."
                text_tokens = self._approximate_token_count(text)

            if accumulated_tokens + text_tokens > self.max_centroid_tokens and selected_texts:
                break

            selected_texts.append(text)
            accumulated_tokens += text_tokens

        return selected_texts, accumulated_tokens, centroid.tolist()

    def cluster_events(
        self,
        events: List[RawTrendEvent],
        window_hours: float = 4.0
    ) -> List[TrendCluster]:
        """
        Сквозной процесс кластеризации и детекции трендов:
        1. Дедупликация.
        2. Векторизация и L2-нормализация.
        3. Редукция размерности (Curse of Dimensionality).
        4. Кластеризация HDBSCAN (fallback DBSCAN).
        5. Расчет velocity_score и density_spike.
        6. Центроидная выборка с усечением токенов.
        """
        unique_events = self.deduplicate_events(events)
        if len(unique_events) < self.min_cluster_size:
            logger.info(f"[TrendClusterer] Недостаточно уникальных данных для кластеризации ({len(unique_events)} < {self.min_cluster_size})")
            return []

        # 1. Векторизация
        raw_texts = [e.raw_text for e in unique_events]
        embeddings = self._vectorize_texts(raw_texts)

        # 2. Снижение размерности
        reduced_embeddings = self._reduce_dimensions(embeddings)

        # 3. Плотностная кластеризация
        labels = np.array([-1] * len(unique_events))
        if HAS_SKLEARN:
            try:
                # HDBSCAN на евклидовом расстоянии поверх L2-нормализованных векторов
                hdb = HDBSCAN(
                    min_cluster_size=self.min_cluster_size,
                    min_samples=self.min_samples,
                    metric="euclidean",
                    cluster_selection_method="eom"
                )
                labels = hdb.fit_predict(reduced_embeddings)
                # Если HDBSCAN посчитал весь датасет шумом (например, при малом N), применяем DBSCAN
                if set(labels) <= {-1}:
                    db = DBSCAN(eps=0.45, min_samples=self.min_samples, metric="cosine")
                    labels = db.fit_predict(embeddings)
            except Exception as e:
                logger.warning(f"[TrendClusterer] HDBSCAN не сошелся: {e}. Fallback на DBSCAN.")
                try:
                    db = DBSCAN(eps=0.45, min_samples=self.min_samples, metric="cosine")
                    labels = db.fit_predict(embeddings)
                except Exception:
                    pass


        # 4. Анализ плотности и скорости нарастания (Velocity Math)
        unique_labels = set(labels)
        if -1 in unique_labels:
            unique_labels.remove(-1)

        clusters: List[TrendCluster] = []
        n_clusters = max(1, len(unique_labels))
        # Ожидаемая скорость на один кластер при равномерном распределении инфопотока
        expected_cluster_velocity = max(0.1, (len(unique_events) / n_clusters) / max(0.5, window_hours))

        for lbl in unique_labels:
            indices = np.where(labels == lbl)[0].tolist()
            cluster_count = len(indices)
            if cluster_count < self.min_cluster_size:
                continue

            # Расчет временного диапазона кластера
            cluster_times = [unique_events[i].timestamp for i in indices]
            min_time = min(cluster_times)
            max_time = max(cluster_times)
            timespan_sec = max(60.0, (max_time - min_time).total_seconds())
            timespan_h = timespan_sec / 3600.0

            # Velocity: количество упоминаний в час
            velocity = cluster_count / max(0.25, timespan_h)
            density_spike = velocity / expected_cluster_velocity

            # Доля кластера в общем потоке (концентрация темы)
            share = cluster_count / len(unique_events)
            if share >= 0.20 and density_spike < self.min_density_spike:
                density_spike = max(density_spike, round(self.min_density_spike * 1.05, 2))

            if density_spike < self.min_density_spike:
                # Кластер не превышает порог статистической аномальности
                continue


            # Извлечение центроидных текстов с жестким контролем токенов
            rep_texts, total_tokens, centroid_vec = self._extract_centroid_texts(
                cluster_indices=indices,
                events=unique_events,
                embeddings=embeddings
            )

            # Выборка медиа-ссылок
            media_samples = []
            for i in indices:
                for m in unique_events[i].media_links:
                    if m and m not in media_samples and len(media_samples) < 5:
                        media_samples.append(m)

            cluster_id = f"tc_{uuid.uuid4().hex[:8]}"
            tc = TrendCluster(
                cluster_id=cluster_id,
                total_samples=cluster_count,
                velocity_score=round(velocity, 2),
                density_spike=round(density_spike, 2),
                cluster_centroid_vector=centroid_vec[:20],  # компактный срез центроида
                centroid_representative_texts=rep_texts,
                total_representative_tokens=total_tokens,
                media_samples=media_samples,
                timespan_hours=round(timespan_h, 2),
            )
            clusters.append(tc)

        # Сортировка по степени аномальности (density_spike)
        clusters.sort(key=lambda x: x.density_spike, reverse=True)
        logger.info(f"[TrendClusterer] 🎯 Найдено {len(clusters)} статистически аномальных тренд-кластеров.")
        return clusters

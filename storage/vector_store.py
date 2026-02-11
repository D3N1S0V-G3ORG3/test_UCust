"""
Интерфейс и заглушка векторного хранилища эмбеддингов.
"""

from __future__ import annotations

from typing import List, Tuple, Optional


class VectorRecord:
    """
    Запись эмбеддинга текста.

    Используется в векторном хранилище эмбеддингов для проверки дублей.
    """

    def __init__(self, text_id: str, embedding: List[float], metadata: Optional[dict] = None) -> None:
        """
        Инициализирует запись эмбеддинга.

        :param text_id: идентификатор текста.
        :param embedding: вектор эмбеддинга.
        :param metadata: дополнительные метаданные.
        """

        self.text_id = text_id
        self.embedding = embedding
        self.metadata = metadata or {}


class VectorStore:
    """
    Базовый интерфейс векторного хранилища эмбеддингов.

    Позволяет хранить эмбеддинги постов и проверять уникальность контента.
    """

    def add_embedding(self, record: VectorRecord) -> None:
        """
        Добавляет эмбеддинг в хранилище.
        """

        raise NotImplementedError

    def is_duplicate(self, embedding: List[float], threshold: float = 0.9) -> Tuple[bool, float]:
        """
        Проверяет, является ли эмбеддинг дубликатом.

        :param embedding: эмбеддинг нового текста.
        :param threshold: порог сходства.
        :return: (дубликат?, метрика сходства).
        """

        raise NotImplementedError

    def embed_text(self, text: str) -> List[float]:
        """
        Заглушка получения эмбеддинга.

        В реальной системе сюда подключается ChromaDB/FAISS.
        """

        raise NotImplementedError

    def check_uniqueness(self, embedding: List[float], metadata: Optional[dict] = None) -> float:
        """
        Семантическое сопоставление с учетом метаданных (metadata filtering).

        :return: оценка уникальности в диапазоне [0.0, 1.0].
        """

        raise NotImplementedError

    def semantic_filter(self, embedding: List[float], metadata: Optional[dict] = None) -> float:
        """
        Семантическая фильтрация по метаданным проекта (город, ниша).

        Имитирует поиск похожих постов и возвращает оценку уникальности.
        """

        raise NotImplementedError


class InMemoryVectorStore(VectorStore):
    """
    Простая заглушка векторного хранилища эмбеддингов.

    Хранит эмбеддинги в памяти и применяет косинусное сходство.
    """

    def __init__(self) -> None:
        """
        Создает пустое хранилище.
        """

        self._records: List[VectorRecord] = []
        self._by_niche: dict = {}
        self._by_city: dict = {}

    def count(self) -> int:
        """
        Возвращает количество записей в хранилище.
        """

        return len(self._records)

    def add_embedding(self, record: VectorRecord) -> None:
        """
        Добавляет эмбеддинг в память.
        """

        self._records.append(record)
        niche = record.metadata.get("niche") if record.metadata else None
        city = record.metadata.get("city") if record.metadata else None
        if niche:
            self._by_niche.setdefault(niche, []).append(record.embedding)
        if city:
            self._by_city.setdefault(city, []).append(record.embedding)

    def is_duplicate(self, embedding: List[float], threshold: float = 0.9) -> Tuple[bool, float]:
        """
        Проверяет сходство эмбеддинга с уже сохраненными.
        """

        best_score = 0.0
        for record in self._records:
            score = self._cosine_similarity(embedding, record.embedding)
            best_score = max(best_score, score)
        return best_score >= threshold, best_score

    def embed_text(self, text: str) -> List[float]:
        """
        Генерирует псевдо-эмбеддинг на основе статистики текста.

        Используется как заглушка для ChromaDB/FAISS.
        """

        length = float(len(text)) or 1.0
        vowels = sum(1 for ch in text.lower() if ch in "аеёиоуыэюя")
        consonants = sum(1 for ch in text.lower() if ch.isalpha() and ch not in "аеёиоуыэюя")
        words = len(text.split()) or 1
        return [length / 1000.0, vowels / length, consonants / length, words / 100.0]

    def check_uniqueness(self, embedding: List[float], metadata: Optional[dict] = None) -> float:
        """
        Алгоритм семантического сопоставления.
        Проверяет дубликаты с учетом ниши проекта (Metadata Filtering).
        """

        return self.semantic_filter(embedding, metadata)

    def semantic_filter(self, embedding: List[float], metadata: Optional[dict] = None) -> float:
        """
        Семантическая фильтрация по метаданным проекта (город, ниша).

        Возвращает uniqueness_score на основе максимального сходства
        в рамках заданных контекстов.
        """

        meta = metadata or {}
        niche = meta.get("niche")
        city = meta.get("city")
        candidates: List[List[float]] = []

        if niche and niche in self._by_niche:
            candidates.extend(self._by_niche[niche])
        if city and city in self._by_city:
            candidates.extend(self._by_city[city])

        if not candidates:
            return 1.0

        best_score = 0.0
        for candidate in candidates:
            best_score = max(best_score, self._cosine_similarity(embedding, candidate))
        return max(0.0, 1.0 - best_score)

    @staticmethod
    def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        """
        Вычисляет косинусное сходство двух векторов.
        """

        if not vec_a or not vec_b or len(vec_a) != len(vec_b):
            return 0.0
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = sum(a * a for a in vec_a) ** 0.5
        norm_b = sum(b * b for b in vec_b) ** 0.5
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)

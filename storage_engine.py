"""
Пример модулей хранения для комплекса «UCust.AI».
"""

from __future__ import annotations

from typing import Dict, List, Optional

from storage.vector_store import InMemoryVectorStore, VectorRecord


class SQLStorage:
    """
    Модуль хранения структурированных данных проекта (PostgreSQL).

    Описывает цепочку: Клиент -> Продукт -> Анкета.
    """

    def __init__(self) -> None:
        """
        Создает внутренние реестры для хранения сущностей проекта.
        """

        self._profiles: List[Dict[str, str]] = []

    def save_questionnaire(self, payload: Dict[str, str]) -> int:
        """
        Сохраняет анкету пользователя и возвращает идентификатор записи.
        """

        self._profiles.append(payload)
        return len(self._profiles)


class VectorSearch:
    """
    Модуль семантического анализа и поиска дублей (ChromaDB).

    Описывает цепочку: Текст -> Эмбеддинг -> Проверка на плагиат.
    """

    def __init__(self) -> None:
        """
        Инициализирует векторное хранилище для поиска дублей.
        """

        self._vector_store = InMemoryVectorStore()

    def add_post(self, text: str, metadata: Optional[Dict[str, str]] = None) -> None:
        """
        Добавляет пост в векторное хранилище с метаданными проекта.
        """

        embedding = self._vector_store.embed_text(text)
        record = VectorRecord(text_id=f"post-{self._vector_store.count() + 1}", embedding=embedding, metadata=metadata)
        self._vector_store.add_embedding(record)

    def semantic_filter(self, text: str, metadata: Optional[Dict[str, str]] = None) -> float:
        """
        Семантическая фильтрация входного текста с учетом метаданных.

        Возвращает оценку уникальности для когнитивной проверки контента.
        """

        embedding = self._vector_store.embed_text(text)
        return self._vector_store.semantic_filter(embedding, metadata)


class HybridStorageManager:
    """
    Фасад гибридного хранилища, объединяющий SQL и VectorSearch.

    Обеспечивает целостность данных и синхронизацию метаданных между слоями,
    включая семантическую фильтрацию и координацию агентов при сохранении.
    """

    def __init__(
        self,
        sql_storage: Optional[SQLStorage] = None,
        vector_search: Optional[VectorSearch] = None,
    ) -> None:
        """
        Инициализирует фасад гибридного хранения.
        """

        self.sql_storage = sql_storage or SQLStorage()
        self.vector_search = vector_search or VectorSearch()

    def save_questionnaire(self, payload: Dict[str, str]) -> int:
        """
        Сохраняет анкету пользователя в SQL-хранилище.
        """

        return self.sql_storage.save_questionnaire(payload)

    def evaluate_and_store_post(self, text: str, metadata: Dict[str, str]) -> float:
        """
        Оценивает уникальность и сохраняет пост в векторном слое.

        Используется как точка детерминированного вызова для аналитики.
        """

        uniqueness_score = self.vector_search.semantic_filter(text, metadata)
        self.vector_search.add_post(text, metadata)
        return uniqueness_score

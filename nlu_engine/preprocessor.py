"""
Лингвистический фильтр (заглушка) для очистки текста.
"""

from __future__ import annotations

from typing import List

from schemas.models import SanitizedDataSchema


class PreProcessor:
    """
    Лингвистический фильтр для предварительной обработки текста.

    В реальной системе может использовать ru-en-RoSBERTa для определения
    тональности и нормализации данных.
    """

    def sanitize_data(self, text: str) -> SanitizedDataSchema:
        """
        Имитирует очистку текста и определение тональности.

        :param text: исходный текст.
        :return: очищенный текст, тональность и заметки.
        """

        cleaned = " ".join(text.strip().split())
        sentiment = "нейтральная" if cleaned else "не определена"
        notes: List[str] = ["Очистка пробелов", "Определение тональности: заглушка"]
        technical_log = [
            "Лингвистический фильтр: старт",
            "Лингвистический фильтр: очистка выполнена",
            f"Лингвистический фильтр: тональность={sentiment}",
        ]
        return SanitizedDataSchema(
            text=cleaned,
            sentiment=sentiment,
            notes=notes,
            technical_log=technical_log,
        )

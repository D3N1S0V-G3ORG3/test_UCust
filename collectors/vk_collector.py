"""
Заглушка модуля API-парсинга vk_api.
"""

from __future__ import annotations

from datetime import datetime

from schemas.models import CollectorDataSchema


class VkApiCollector:
    """
    Модуль асинхронного сбора данных из VK.

    Реализован как заглушка, имитирующая работу API-парсера vk_api.
    """

    def collect(self, group_id: str, limit: int = 10) -> CollectorDataSchema:
        """
        Имитирует сбор постов из сообщества VK.

        :param group_id: идентификатор сообщества.
        :param limit: количество постов.
        :return: результат парсинга.
        """

        payload = {
            "group_id": group_id,
            "limit": limit,
            "fetched_at": datetime.utcnow().isoformat(),
            "posts": [
                {"id": i, "text": f"Пост {i} из группы {group_id}", "likes": 50 + i}
                for i in range(1, limit + 1)
            ],
        }
        return CollectorDataSchema(source="vk_api", payload=payload)

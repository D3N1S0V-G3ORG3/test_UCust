"""
Заглушка модуля API-парсинга Telethon.
"""

from __future__ import annotations

from datetime import datetime

from schemas.models import CollectorDataSchema


class TelethonCollector:
    """
    Модуль асинхронного сбора данных из Telegram.

    Реализован как заглушка, имитирующая работу API-парсера Telethon.
    """

    def collect(self, channel: str, limit: int = 10) -> CollectorDataSchema:
        """
        Имитирует сбор сообщений из Telegram-канала.

        :param channel: идентификатор канала.
        :param limit: количество сообщений.
        :return: результат парсинга.
        """

        payload = {
            "channel": channel,
            "limit": limit,
            "fetched_at": datetime.utcnow().isoformat(),
            "messages": [
                {"id": i, "text": f"Сообщение {i} из {channel}", "views": 100 + i}
                for i in range(1, limit + 1)
            ],
        }
        return CollectorDataSchema(source="telethon", payload=payload)

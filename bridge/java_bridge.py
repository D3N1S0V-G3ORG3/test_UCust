"""
API-интерфейс для связи с внешним Java-сервисом.
"""

from __future__ import annotations

from typing import Any, Dict

from schemas.models import KandinskyPromptSchema, PostDraftSchema, UserQuestionnaire


class JavaBridgeClient:
    """
    Клиент для интеграции с Java-backend.

    Отправляет структурированные данные (JSON-контракты) во внешний сервис.
    """

    def __init__(self, base_url: str) -> None:
        """
        Инициализирует клиент.

        :param base_url: базовый URL Java-сервиса.
        """

        self.base_url = base_url.rstrip("/")

    def send_questionnaire(self, questionnaire: UserQuestionnaire) -> Dict[str, Any]:
        """
        Заглушка отправки анкеты пользователя.

        :param questionnaire: анкета из 5 шагов.
        :return: технический лог работы.
        """

        return {
            "endpoint": f"{self.base_url}/questionnaire",
            "payload": questionnaire.model_dump(),
            "status": "stub_sent",
        }

    def send_post_draft(self, draft: PostDraftSchema) -> Dict[str, Any]:
        """
        Заглушка отправки черновика поста.

        :param draft: черновик поста.
        :return: технический лог работы.
        """

        return {
            "endpoint": f"{self.base_url}/post-draft",
            "payload": draft.model_dump(),
            "status": "stub_sent",
        }

    def send_kandinsky_prompt(self, prompt: KandinskyPromptSchema) -> Dict[str, Any]:
        """
        Заглушка отправки промпта для генерации визуалов.

        :param prompt: промпт Kandinsky.
        :return: технический лог работы.
        """

        return {
            "endpoint": f"{self.base_url}/kandinsky-prompt",
            "payload": prompt.model_dump(),
            "status": "stub_sent",
        }

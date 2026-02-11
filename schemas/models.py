"""
Pydantic-модели и JSON-контракты для комплекса «UCust.AI».
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class QuestionnaireStep1(BaseModel):
    """
    Шаг 1 анкеты пользователя.

    Определяет базовые сведения о компании/бренде для последующей
    работы модулей, включая лингвистический фильтр и
    нейросетевой генеративный модуль.
    """

    business_name: str = Field(..., description="Название компании или бренда")
    mission: str = Field(..., description="Миссия и ценности")
    region: str = Field(..., description="Регион присутствия")


class QuestionnaireStep2(BaseModel):
    """
    Шаг 2 анкеты пользователя.

    Фиксирует параметры целевой аудитории, которые используются
    модулем асинхронного сбора данных и аналитическим агентом.
    """

    target_audience: str = Field(..., description="Описание целевой аудитории")
    demographics: str = Field(..., description="Демографические признаки")
    pain_points: str = Field(..., description="Боли и потребности аудитории")


class QuestionnaireStep3(BaseModel):
    """
    Шаг 3 анкеты пользователя.

    Определяет тональность, форматы и ограничения, которые далее
    учитываются агентом-копирайтером и векторным хранилищем эмбеддингов.
    """

    tone_of_voice: str = Field(..., description="Тональность коммуникации")
    content_formats: str = Field(..., description="Предпочтительные форматы контента")
    taboo_topics: str = Field(..., description="Запрещенные темы и слова")


class QuestionnaireStep4(BaseModel):
    """
    Шаг 4 анкеты пользователя.

    Содержит целевые показатели и параметры публикаций, которые
    используются при формировании стратегии и сетки контента.
    """

    goals: str = Field(..., description="Цели коммуникации")
    kpi: str = Field(..., description="KPI/метрики эффективности")
    frequency: str = Field(..., description="Частота публикаций")


class QuestionnaireStep5(BaseModel):
    """
    Шаг 5 анкеты пользователя.

    Собирает данные о конкурентах и референсах для SWOT-анализа
    и последующих генеративных модулей.
    """

    competitors: str = Field(..., description="Ключевые конкуренты")
    references: str = Field(..., description="Референсы и примеры")
    additional_notes: str = Field(..., description="Дополнительные комментарии")


class UserQuestionnaire(BaseModel):
    """
    Полная анкета пользователя из 5 шагов.

    Используется агентом-интервьюером для валидации и сохранения
    в SQL-хранилище и передачи в Java-backend.
    """

    step1: QuestionnaireStep1
    step2: QuestionnaireStep2
    step3: QuestionnaireStep3
    step4: QuestionnaireStep4
    step5: QuestionnaireStep5


class ProjectMetadataSchema(BaseModel):
    """
    Метаданные проекта SMM-кампании.

    Передаются между агентами и могут быть сериализованы в JSON-контракт.
    """

    project_id: Optional[int] = Field(None, description="Идентификатор проекта")
    user_id: Optional[int] = Field(None, description="Идентификатор пользователя")
    name: str = Field(..., description="Название проекта")
    niche: str = Field(..., description="Ниша/отрасль")
    platforms: List[str] = Field(..., description="Платформы продвижения")
    created_at: Optional[datetime] = Field(None, description="Дата создания")


class PublicationHistorySchema(BaseModel):
    """
    Запись истории публикаций.

    Нужна для аудита и контроля повторов в рамках ниши.
    """

    publication_id: Optional[int] = Field(None, description="Идентификатор публикации")
    project_id: int = Field(..., description="Идентификатор проекта")
    platform: str = Field(..., description="Платформа публикации")
    post_text: str = Field(..., description="Текст публикации")
    status: str = Field(..., description="Статус публикации")
    published_at: Optional[datetime] = Field(None, description="Дата публикации")


class CollectorDataSchema(BaseModel):
    """
    Результат работы модулей API-парсинга.

    Объединяет данные из Telethon и vk_api для последующего анализа.
    """

    source: str = Field(..., description="Источник данных")
    payload: dict = Field(..., description="Сырые данные парсинга")


class SWOTResultSchema(BaseModel):
    """
    Результат SWOT-анализа.

    Используется аналитическим агентом как промежуточный артефакт.
    """

    strengths: List[str]
    weaknesses: List[str]
    opportunities: List[str]
    threats: List[str]
    summary: str


class SanitizedDataSchema(BaseModel):
    """
    Результат работы лингвистического фильтра.

    Отражает очищенный текст и оценку тональности.
    """

    text: str
    sentiment: str
    notes: List[str]
    technical_log: List[str] = Field(default_factory=list, description="Технический лог работы фильтра")


class StrategyPlanSchema(BaseModel):
    """
    Результат работы нейросетевого генеративного модуля.

    Формирует общую стратегию для копирайтера и визуального директора.
    """

    strategy: str
    risks: List[str]
    recommendations: List[str]
    technical_log: List[str] = Field(default_factory=list, description="Технический лог генерации стратегии")


class PostDraftSchema(BaseModel):
    """
    Черновик поста для публикации.

    Содержит метку уникальности для проверки векторным хранилищем эмбеддингов.
    """

    text: str
    uniqueness_score: float
    duplicates_found: bool


class GridTileSchema(BaseModel):
    """
    Элемент контентной сетки (плитка).

    Используется визуальным директором для описания будущего контента.
    """

    tile_id: int
    title: str
    description: str


class GridPlanSchema(BaseModel):
    """
    План сетки контента.

    Хранит список плиток и применяется при генерации промптов.
    """

    tiles: List[GridTileSchema]


class KandinskyPromptSchema(BaseModel):
    """
    Технический промпт для генерации визуалов.

    Используется как контракт для внешнего Java-сервиса.
    """

    prompt_text: str
    style: str
    aspect_ratio: str

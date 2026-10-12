"""
File: ai/schemas/pipeline_state.py
Строгий типизированный контракт сквозного состояния (Pipeline State) для UCust AI.
Заменяет неструктурированные словари (dict) во всех сервисах и оркестраторах.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ContentFormatEnum(str, Enum):
    POST = "post"
    CAROUSEL = "carousel"
    POLL = "poll"
    QUIZ = "quiz"
    STORYTELLING = "storytelling"
    PUZZLE = "puzzle"
    SWIPE_PUZZLE = "swipe_puzzle"
    CRYPTEX = "cryptex"


class PipelineState(BaseModel):
    """
    Единый типизированный контекст состояния конвейера генерации.
    Поддерживает валидацию, изоляцию тенантов и телеметрию на каждом шаге.
    """

    # 1. Идентификация сессии и тенанта
    session_id: str = Field(..., description="Уникальный ID сессии/задачи")
    tenant_id: str = Field(default="default_tenant", description="Идентификатор изолированного тенанта")
    user_id: str = Field(default="default_user", description="ID пользователя/клиента")

    # 2. Исходные параметры задачи
    company_name: str = Field(default="", description="Название компании/бренда")
    niche: str = Field(default="бизнес", description="Отрасль / сфера бизнеса")
    topic: str = Field(default="", description="Тема генерации или продукта")
    tone_of_voice: str = Field(default="Экспертный, лаконичный, живой", description="Tone of Voice")
    target_format: ContentFormatEnum = Field(default=ContentFormatEnum.POST, description="Целевой формат публикации")

    # 3. Входные медиа, заметки и ссылки
    attachments: List[Dict[str, Any]] = Field(default_factory=list, description="Исходные фото, ссылки или файлы")
    raw_notes: Optional[str] = Field(None, description="Дополнительные заметки и пожелания")
    telegram_channel: Optional[str] = Field(None, description="Целевой Telegram-канал для парсинга/публикации")
    website_url: Optional[str] = Field(None, description="URL сайта компании")

    # 4. Этап 1: Brand DNA & Grounded Knowledge (RAG / PIM)
    brand_dna: Optional[Dict[str, Any]] = Field(None, description="Извлеченный паспорт бренда (Brand DNA)")
    rag_facts: List[str] = Field(default_factory=list, description="Верифицированные факты из Clean RAG")
    is_grounded: bool = Field(default=False, description="Подтверждена ли фактология паспортом качества")

    # 5. Этап 2: Сгенерированный контент
    draft_text: str = Field(default="", description="Сгенерированный текст публикации")
    poll_payload: Optional[Dict[str, Any]] = Field(None, description="Параметры опроса или квиза")
    puzzle_row_albums: Optional[List[List[str]]] = Field(None, description="Нарезка интерактивного пазла")

    # 6. Этап 3: OTK аудит и критика (Charlie Munger + Fact-Check)
    critic_score: float = Field(default=1.0, description="Оценка качества от 0.0 до 1.0")
    critic_flaws: List[str] = Field(default_factory=list, description="Замечания аудитора качества")
    fact_check_passed: bool = Field(default=True, description="Флаг прохождения фактчекинга")

    # 7. Этап 4: Рендер визуала (ComfyUI GPU)
    photo_paths: List[str] = Field(default_factory=list, description="Пути к сгенерированным локальным изображениям")
    visual_prompt: str = Field(default="", description="Финальный промпт для рендера ComfyUI")

    # 8. Этап 5: Статус публикации и телеметрия
    is_published: bool = Field(default=False, description="Статус отправки в канал")
    publication_result: Optional[Dict[str, Any]] = Field(None, description="Ответ API соцсетей (Telegram/VK)")
    telemetry: Dict[str, float] = Field(default_factory=dict, description="Хронометраж выполнения по этапам в секундах")
    error: Optional[str] = Field(None, description="Текст критической ошибки при сбое пайплайна")


__all__ = ["PipelineState", "ContentFormatEnum"]

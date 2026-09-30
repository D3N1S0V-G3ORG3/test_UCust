"""
Pydantic-модели и JSON-контракты для комплекса «UCust.AI».
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator


class CopywritingFramework(str, Enum):
    PAS = "PAS"
    AIDA = "AIDA"
    PMHS = "PMHS"  # Pain, More Pain, Hope, Solution


FRAMEWORK_PROMPTS = {
    CopywritingFramework.PAS: """
Твоя задача — написать текст строго по структуре PAS:
1. PROBLEM (Проблема): Начни с боли целевой аудитории. Зацепи внимание вопросом или фактом.
2. AGITATION (Усиление): Покажи, что будет, если проблему не решить. Нагнетай эмоции, добавь конкретики.
3. SOLUTION (Решение): Представь наш продукт/услугу как идеальное и единственно верное решение проблемы. Призови к действию (CTA).
""",
    CopywritingFramework.AIDA: """
Твоя задача — написать текст строго по структуре AIDA:
1. ATTENTION (Внимание): Яркий заголовок или нестандартный факт, заставляющий остановиться.
2. INTEREST (Интерес): Удержи внимание, раскрой интригу, приведи интересные цифры из SWOT-анализа.
3. DESIRE (Желание): Опиши выгоды. Заставь читателя захотеть продукт, покажи трансформацию "до/после".
4. ACTION (Действие): Четкий и понятный призыв к действию (CTA) — что нужно сделать прямо сейчас.
""",
    CopywritingFramework.PMHS: """
Твоя задача — написать текст строго по структуре PMHS:
1. PAIN (Боль): Определи ключевую проблему читателя.
2. MORE PAIN (Еще больше боли): Углуби проблему, покажи негативные последствия бездействия.
3. HOPE (Надежда): Дай надежду на решение и положительные изменения.
4. SOLUTION (Решение): Предложи конкретное решение и призвание к действию (CTA).
""",
}


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

    Содержит метку уникальности, результаты фактчекинга и ссылки на сгенерированные медиа-артефакты (изображения, видео, аудио).
    """

    text: str
    uniqueness_score: float
    duplicates_found: bool
    fact_checked: bool = Field(default=False, description="Флаг успешного прохождения фактчекинга")
    removed_claims: List[str] = Field(default_factory=list, description="Список удаленных несоответствий/галлюцинаций")
    image_url: Optional[str] = Field(None, description="URL сгенерированного изображения")
    video_url: Optional[str] = Field(None, description="URL сгенерированного видео (LTX-2.3)")
    audio_url: Optional[str] = Field(None, description="URL сгенерированной аудиодорожки (LTX-2.3)")
    media_url: Optional[str] = Field(None, description="Универсальный URL основного медиа-файла")
    local_video_path: Optional[str] = Field(None, description="Локальный путь к видеофайлу на сервере (ComfyUI Output)")
    local_audio_path: Optional[str] = Field(None, description="Локальный путь к аудиофайлу на сервере (ComfyUI Output)")
    local_image_path: Optional[str] = Field(None, description="Локальный путь к файлу изображения на сервере")


class GridTileSchema(BaseModel):
    """
    Элемент контентной сетки (плитка).

    Используется визуальным директором для описания будущего мультимодального видео-контента.
    """

    tile_id: int
    title: str
    description: str


class GridPlanSchema(BaseModel):
    """
    План сетки контента.

    Хранит список плиток и применяется при генерации видео и аудио промптов LTX-2.3.
    """

    tiles: List[GridTileSchema]


class LTX23ConfigSchema(BaseModel):
    """
    Конфигурация 6 обязательных компонентов мультимодальной архитектуры LTX-2.3 (ComfyUI Headless API).
    """

    checkpoint: str = Field(default="ltx-2.3-22b-dev.safetensors", description="1. Базовый чекпоинт (Модель диффузии)")
    text_encoder: str = Field(default="gemma_3_12B_it_fp4_mixed.safetensors", description="2. Текстовый энкодер Google Gemma 3 12B IT FP4")
    lora: str = Field(default="ltx-2.3-22b-distilled-lora-384.safetensors", description="3. LoRA для дистилляции и ускорения генерации")
    spatial_upscaler: str = Field(default="ltx-2.3-spatial-upscaler-x2-1.1.safetensors", description="4. Пространственный апскейлер x2 в latent space")
    video_vae: str = Field(default="LTX23_video_vae_bf16.safetensors", description="5. Видео VAE автоэнкодер")
    audio_vae: str = Field(default="LTX23_audio_vae_bf16.safetensors", description="6. Аудио VAE автоэнкодер")


class LTX23PromptSchema(BaseModel):
    """
    Технический промпт и ComfyUI JSON-workflow для генерации видео со звуком на мультимодальном движке LTX-2.3.
    """

    video_prompt: str = Field(..., description="Промпт для генерации динамического видеоряда")
    audio_prompt: str = Field(..., description="Промпт для генерации синхронной аудиодорожки")
    motion_bucket_id: int = Field(default=127, description="Коэффициент динамики движения")
    fps: int = Field(default=24, description="Частота кадров в секунду")
    aspect_ratio: str = Field(default="16:9", description="Соотношение сторон кадра (16:9, 9:16, 1:1)")
    duration_seconds: float = Field(default=5.0, description="Длительность генерируемого видеоклипа")
    config: LTX23ConfigSchema = Field(default_factory=LTX23ConfigSchema, description="Конфигурация 6 компонентов LTX-2.3")
    comfyui_workflow: Dict[str, Any] = Field(default_factory=dict, description="JSON-workflow граф для ComfyUI Headless API")


class PostGenerationTaskSchema(BaseModel):
    """
    Pydantic-схема задачи для генерации поста.
    """

    user_id: str = Field(..., description="Идентификатор пользователя")
    framework: CopywritingFramework = Field(
        default=CopywritingFramework.PAS,
        description="Фреймворк копирайтинга (PAS, AIDA, PMHS)",
    )


class PublishRequestSchema(BaseModel):
    """
    Input schema for publishing a Human-in-the-Loop post to target platforms (Telegram, VK, Instagram, OK, MAX).
    """

    platforms: Optional[List[str]] = Field(
        default=None,
        description="List of target platforms (e.g., ['telegram', 'vk', 'instagram', 'ok', 'max'])",
    )
    target_platforms: List[str] = Field(
        default=["telegram"],
        description="List of target platforms (e.g., ['telegram', 'vk', 'instagram', 'ok', 'max'])",
    )
    custom_caption: Optional[str] = Field(
        default=None,
        description="Optional custom caption override provided by user prior to publishing",
    )


class PendingPostSchema(BaseModel):
    """
    Export schema for posts awaiting human-in-the-loop review in the web UI.
    """

    job_id: int = Field(..., description="FSM Task / Job ID")
    user_id: str = Field(..., description="External user identifier")
    status: str = Field(..., description="FSM Task Status")
    post_text: Optional[str] = Field(None, description="Generated draft post text")
    video_url: Optional[str] = Field(None, description="URL for video preview")
    audio_url: Optional[str] = Field(None, description="URL for audio preview")
    media_url: Optional[str] = Field(None, description="URL for combined media preview")
    local_video_path: Optional[str] = Field(None, description="Local server file path for video")
    local_audio_path: Optional[str] = Field(None, description="Local server file path for audio")
    uniqueness_score: float = Field(default=1.0, description="Vector uniqueness score")
    duplicates_found: bool = Field(default=False, description="Duplicate detection flag")


# Каноническая карта алиасов каналов для Shift-Left валидации (Write Path)
CHANNEL_CANONICAL_MAP: Dict[str, str] = {
    "telegram": "telegram",
    "tg": "telegram",
    "телеграм": "telegram",
    "телеграм-канал": "telegram",
    "vk": "vk",
    "vkontakte": "vk",
    "вк": "vk",
    "вконтакте": "vk",
    "ok": "ok",
    "odnoklassniki": "ok",
    "ок": "ok",
    "одноклассники": "ok",
    "max_messenger": "max_messenger",
    "max": "max_messenger",
    "messenger": "max_messenger",
    "мессенджер": "max_messenger",
    "instagram": "instagram",
    "inst": "instagram",
    "инстаграм": "instagram",
}


# Максимальное количество одновременно подключенных каналов (Boundary Limit / Circuit Breaker)
MAX_CONNECTED_CHANNELS: int = 10


class ChannelRegistrationDTO(BaseModel):
    """
    Shift-Left Валидация (Write Path):
    Применяется при сохранении профиля, регистрации каналов и обработке HTTP-запросов (POST/PUT).
    Принимает любые пользовательские форматы (алиасы, URL-мапы, флаги), нормализует их,
    проверяет лимит MAX_CONNECTED_CHANNELS и возвращает чистый канонический массив строк List[str].
    """
    channels: List[str] = Field(
        default_factory=list,
        max_length=MAX_CONNECTED_CHANNELS,
        description=f"Канонический список каналов для записи в БД (макс. {MAX_CONNECTED_CHANNELS})"
    )

    @field_validator("channels", mode="before")
    @classmethod
    def normalize_and_limit(cls, raw_data: Any) -> List[str]:
        if raw_data is None:
            return []

        extracted: List[str] = []

        if isinstance(raw_data, dict):
            for ch_name, ch_val in raw_data.items():
                if isinstance(ch_val, bool):
                    if ch_val:
                        extracted.append(str(ch_name))
                elif isinstance(ch_val, dict):
                    if ch_val.get("is_active", True) and not ch_val.get("disabled", False):
                        extracted.append(str(ch_name))
                elif isinstance(ch_val, str):
                    if ch_val.strip() and ch_val.lower() not in ("false", "0", "none", "null", "disabled"):
                        extracted.append(str(ch_name))
                elif isinstance(ch_val, (int, float)):
                    if ch_val > 0:
                        extracted.append(str(ch_name))
        elif isinstance(raw_data, (list, tuple, set)):
            for item in raw_data:
                if isinstance(item, str):
                    if item.strip():
                        extracted.append(item.strip())
                elif isinstance(item, dict):
                    name = item.get("name") or item.get("platform") or item.get("channel")
                    if name and item.get("is_active", True):
                        extracted.append(str(name))
                else:
                    raise ValueError(f"Unsupported item in channels sequence: {type(item)} ({item})")
        elif isinstance(raw_data, str):
            if "," in raw_data:
                extracted.extend([s.strip() for s in raw_data.split(",") if s.strip()])
            elif raw_data.strip():
                extracted.append(raw_data.strip())
        else:
            raise ValueError(f"Unsupported channels raw data type: {type(raw_data)} (expected list, dict, or str)")

        # Канонизация и дедупликация
        canonical_list: List[str] = []
        for ch in extracted:
            clean = ch.lower().strip()
            norm = CHANNEL_CANONICAL_MAP.get(clean, clean)
            if norm and norm not in canonical_list:
                canonical_list.append(norm)

        # Граничное ограничение (Circuit Breaking)
        if len(canonical_list) > MAX_CONNECTED_CHANNELS:
            raise ValueError(
                f"Exceeded maximum allowed connected channels limit ({MAX_CONNECTED_CHANNELS}), got {len(canonical_list)}"
            )

        return canonical_list


class ActiveChannelsDTO(BaseModel):
    """
    Строгий DTO слоя чтения (Read Path - O(1) CPU Fast Path):
    Принимает ИСКЛЮЧИТЕЛЬНО каноничный List[str].
    Вся поддержка Dict[str, bool] удалена (Dead Code Elimination).
    Любое отклонение от List[str] является нарушением Single Source of Truth и вызывает исключение.
    """
    channels: List[str] = Field(
        default_factory=list,
        max_length=MAX_CONNECTED_CHANNELS,
        description=f"Строгий список каналов (макс. {MAX_CONNECTED_CHANNELS})"
    )

    @field_validator("channels", mode="before")
    @classmethod
    def require_strict_list(cls, raw_data: Any) -> List[str]:
        if raw_data is None:
            return []
        if isinstance(raw_data, list) and all(isinstance(x, str) for x in raw_data):
            if len(raw_data) > MAX_CONNECTED_CHANNELS:
                raise ValueError(
                    f"Corrupted DB state: channels count {len(raw_data)} exceeds max limit ({MAX_CONNECTED_CHANNELS})"
                )
            return raw_data
        raise ValueError(
            f"Corrupted DB state: Single Source of Truth violated. Expected List[str], got {type(raw_data)}"
        )


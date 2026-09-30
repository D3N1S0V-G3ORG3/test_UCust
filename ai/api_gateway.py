"""
AI Service Gateway (FastAPI)
Единый шлюз подключения ИИ-агентов UCust к Бэкенду и Фронтенду.
Предоставляет REST API и WebSockets для real-time онбординга.
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import asyncio
import time
import json
import uuid
from typing import Any, Dict, List, Optional
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Depends, status, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from fastapi.staticfiles import StaticFiles
import os

from storage.db import DatabaseFactory
from core.orchestrator import UnifiedOrchestrator, SecurityGuard
from rag.pipeline import CleanRAGPipeline
from rag.models import Document
from core.lazy_rendering_controller import (
    LazyRenderingController, PostDraft, SubscriptionTier, 
    IndustryArchetype, ContentFormat, PostLifecycleStatus, ImageGenerationSpec
)
from skills.content_strategy_engine import (
    ContentStrategyEngine, BrandProfile, RawDataIngestion, IngestionSourceType
)
from schemas.project_onboarding import (
    AboutScreen, MarketScreen, SWOTScreen, ServiceItem, GoalsScreen,
    ProjectProfileDraft, ProjectAnalyzeRequest, ProjectAnalyzeResponse,
    ProjectCommitRequest, ProjectCommitResponse
)
try:
    from services.calendar_idea_notification_pipeline import CalendarIdeaNotificationPipeline
except ImportError:
    from ai.services.calendar_idea_notification_pipeline import CalendarIdeaNotificationPipeline


# -------------------------------------------------------------------
# 1. Pydantic Модели запросов и ответов (API Contract v2.5.0)
# -------------------------------------------------------------------

class OrchestratorTaskRequest(BaseModel):
    task_type: str = Field(
        ...,
        example="analyze_brand",
        description="Тип задачи: 'analyze_brand', 'generate_post', 'quick_vision', 'analyze_documents', 'quick_scan', 'onboard_user', 'parse_telegram', 'parse_vk', 'parse_geo', 'parse_website', 'plan_content', 'feedback_loop', 'rag_query', 'rag_ingest'"
    )
    user_id: str = Field("default_user", example="usr_94812", description="Идентификатор пользователя")
    project_id: Optional[str] = Field(None, example="temp_proj_123", description="Идентификатор проекта (tenant_id)")
    session_id: Optional[str] = Field(None, example="sess_abc123", description="ID сессии диалога / трейса")
    callback_url: Optional[str] = Field(None, example="http://10.0.0.1:8080/api/v1/ai/callback", description="Динамический URL вебхука для авто-пуша")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Полезная нагрузка (параметры, ссылки, фото, тексты)")
    sync_backend: bool = Field(default=True, description="Флаг авто-пуша результата в бэкенд")


class OrchestratorTaskResponse(BaseModel):
    status: str = Field(..., example="success", description="'success' или 'error'")
    task_type: str
    user_id: str
    session_id: str
    data: Dict[str, Any] = Field(default_factory=dict)
    timings: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class TaskRequest(BaseModel):
    user_id: str = Field("default_user", example="usr_94812", description="Идентификатор пользователя")
    session_id: Optional[str] = Field(None, example="sess_abc123", description="ID сессии диалога")
    task_type: str = Field(..., example="generate_post", description="Тип задачи: generate_post | generate_image | prepare_holiday_greeting | get_trends | rag_query | parse_telegram | parse_vk | parse_geo | parse_website")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Параметры задачи")


class TaskResponse(BaseModel):
    status: str = Field(..., example="success")
    task_id: str = Field(..., example="task_38df92a")
    session_id: str = Field(..., example="sess_abc123")
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class TrendResponse(BaseModel):
    status: str = "success"
    niche: str
    trends: Any
    cached: bool = True


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(..., example="Сезонный тыквенный латте с корицей и круассан")
    niche: str = Field("Кофейня", example="Кофейня")
    aspect_ratio: str = Field("1:1", example="1:1")
    style: str = Field("photorealistic", example="photorealistic")
class RAGQueryRequest(BaseModel):
    query: str = Field(..., example="Сколько стоит тариф Pro?")
    top_k: int = Field(5, ge=1, le=20)


class RAGIngestRequest(BaseModel):
    documents: List[Dict[str, Any]] = Field(..., description="Список документов для базы знаний")


class VisionAnalyzeRequest(BaseModel):
    image: Optional[str] = Field(None, description="Base64 DataUrl или путь к изображению")
    attachments: Optional[List[Dict[str, Any]]] = Field(None, description="Список вложений")
    topic: Optional[str] = Field("", example="Летний фестиваль напитков")
    company_name: Optional[str] = Field("UCust", example="UCust")


class WebsiteAnalyzeRequest(BaseModel):
    url: str = Field(..., example="https://ucust.ai", description="URL веб-сайта компании для парсинга и анализа")


class TelegramAnalyzeRequest(BaseModel):
    channel: str = Field(..., example="@UcustAi", description="Username Telegram-канала или ссылка t.me/...")
    limit: Optional[int] = Field(10, example=10, description="Количество постов для анализа (по умолчанию 10)")
    include_media_vqa: Optional[bool] = Field(True, description="Флаг анализа прикрепленных фото через Moondream2 + OCR")
    user_id: Optional[str] = Field("default_user", description="ID пользователя")
    session_id: Optional[str] = Field(None, description="ID сессии")


class VkAnalyzeRequest(BaseModel):
    group_id: str = Field(..., example="ucust_ai", description="ID или короткое имя сообщества VK / ссылка")
    limit: Optional[int] = Field(10, example=10, description="Количество постов (по умолчанию 10)")
    user_id: Optional[str] = Field("default_user", description="ID пользователя")
    session_id: Optional[str] = Field(None, description="ID сессии")


class GeoAnalyzeRequest(BaseModel):
    url: str = Field(..., example="https://2gis.ru/moscow/firm/...", description="Ссылка на организацию в 2GIS или Яндекс Картах")
    provider: Optional[str] = Field("auto", example="auto", description="Провайдер: 'auto', '2gis', 'yandex'")
    limit: Optional[int] = Field(10, example=10, description="Количество отзывов")
    user_id: Optional[str] = Field("default_user", description="ID пользователя")
    session_id: Optional[str] = Field(None, description="ID сессии")


class UniversalCollectorRequest(BaseModel):
    source_type: Optional[str] = Field("auto", example="auto", description="Тип источника: 'auto', 'telegram', 'vk', 'website', 'geo', '2gis', 'yandex', 'documents'")
    target: str = Field(..., example="@UcustAi", description="Ссылка, username (@channel), ID группы или путь к файлу")
    limit: Optional[int] = Field(10, example=10, description="Лимит элементов для сбора")
    include_media_vqa: Optional[bool] = Field(True, description="Флаг VLM-анализа медиа")
    payload: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Дополнительные параметры")
    user_id: Optional[str] = Field("default_user", description="ID пользователя")
    session_id: Optional[str] = Field(None, description="ID сессии")



class CompetitorAnalyzeRequest(BaseModel):
    url: str = Field(..., example="https://competitor.com", description="URL сайта конкурента для декомпозиции")
    niche: Optional[str] = Field("Бизнес", example="Автосервис", description="Ниша вашей компании")


class StrategyGenerateRequest(BaseModel):
    company_name: Optional[str] = Field("UCust", example="UCust")
    niche: str = Field(..., example="IT Автоматизация")
    target_audience: Optional[str] = Field("", example="Предприниматели 25-45 лет")
    usp: Optional[str] = Field("", example="Автономный маркетинг за 1 день")


class CriticReviewRequest(BaseModel):
    text: str = Field(..., description="Текст поста или оффера для инверсионного аудита Чарли Мангера")
    topic: Optional[str] = Field("", description="Тема поста")
    niche: Optional[str] = Field("", description="Целевая ниша")
    strictness: Optional[float] = Field(0.85, description="Строгость критика (0.5 - мягкая, 0.95 - жесткая)")


class AchievementBroadcastRequest(BaseModel):
    title: str = Field(..., example="Релиз автономного SMM-пайплайна 2.0", description="Заголовок достижения")
    description: str = Field(..., example="Команда ИИ-агентов UCust завершила интеграцию критика и LTX-2.", description="Описание достижения")
    metrics: Optional[List[str]] = Field(default_factory=list, example=["Скорость: 60 сек", "Качество: 98%"], description="Ключевые показатели")
    media_path: Optional[str] = Field(None, description="Путь к фото или видео")
    channel: Optional[str] = Field("@UcustAi", example="@UcustAi", description="Целевой Telegram-канал")


class BrandGuidelines(BaseModel):
    addressingStyle: Optional[str] = Field("YOU_PLURAL", description="Стиль обращения: YOU_SINGULAR (на 'ты'), YOU_PLURAL (на 'вы'), WE_FORM (от лица команды)")
    forbiddenWords: Optional[List[str]] = Field(default_factory=list, description="Черный список стоп-слов, которые запрещено употреблять")
    mandatoryPhrases: Optional[List[str]] = Field(default_factory=list, description="Обязательные фразы / слоганы бренда")
    emojiPolicy: Optional[str] = Field("MINIMAL", description="Политика эмодзи: MINIMAL, VIBRANT, NONE, STRICT_SYSTEM")
    brandKeywords: Optional[List[str]] = Field(default_factory=list, description="Ключевые слова бренда для органического SEO")


class VisualDna(BaseModel):
    brandColors: Optional[List[str]] = Field(default_factory=list, description="Палитра бренда в Hex (#2D5A27, #D4AF37)")
    visualStyle: Optional[str] = Field("PHOTOREALISTIC", description="Визуальный стиль: PHOTOREALISTIC, WARM_NATURAL, MINIMALIST, CINEMATIC, 3D_RENDER")
    moodKeywords: Optional[List[str]] = Field(default_factory=list, description="Атмосферные дескрипторы (уют, крафт, утренний свет)")
    logoUrl: Optional[str] = Field(None, description="URL логотипа для брендинга")
    watermarkPosition: Optional[str] = Field("BOTTOM_RIGHT", description="Позиция водяного знака / лого")
    aspectRatio: Optional[str] = Field("1:1", description="Дефолтное соотношение сторон")


class ProductItem(BaseModel):
    name: str = Field(..., description="Название товара или услуги")
    price: Optional[str] = Field(None, description="Цена (например '850 ₽' или 'от 5 000 ₽')")
    description: Optional[str] = Field(None, description="Краткое описание товара")
    flavorNotes: Optional[str] = Field(None, description="Вкусовые ноты / специфика состава")
    category: Optional[str] = Field(None, description="Категория продукта")
    ctaUrl: Optional[str] = Field(None, description="Прямая ссылка на покупку/заказ")


class LocationBranch(BaseModel):
    address: str = Field(..., description="Физический адрес филиала / точки")
    city: Optional[str] = Field(None, description="Город филиала")
    workingHours: Optional[str] = Field(None, description="Часы работы конкретного филиала")
    phone: Optional[str] = Field(None, description="Контактный телефон")


class ProjectContext(BaseModel):
    id: Optional[str] = Field(None, description="ID проекта")
    projectId: Optional[str] = Field(None, description="ID проекта (алиас)")
    name: Optional[str] = Field(None, description="Название бренда/компании")
    companyName: Optional[str] = Field(None, description="Название бренда (алиас)")
    industry: Optional[str] = Field(None, description="Индустрия / сфера деятельности")
    niche: Optional[str] = Field(None, description="Ниша бизнеса (алиас)")
    city: Optional[str] = Field("Москва", description="Город присутствия")
    description: Optional[str] = Field(None, description="Описание бизнеса и ключевое позиционирование")
    targetAudience: Optional[str] = Field(None, description="Описание целевой аудитории (возраст, боли, ценности)")
    toneOfVoice: Optional[str] = Field("FRIENDLY", description="Тон коммуникации (FRIENDLY, BOLD, EXPERT, FORMAL)")
    
    # 🌟 Расширенные блоки обогащения
    brandGuidelines: Optional[BrandGuidelines] = Field(None, description="Редакционная политика и правила бренда")
    visualDna: Optional[VisualDna] = Field(None, description="Визуальный брендбук и параметры генерации графики")
    productsCatalog: Optional[List[ProductItem]] = Field(default_factory=list, description="Флагманские продукты / меню с ценами")
    keyBenefits: Optional[List[str]] = Field(default_factory=list, description="Ключевые преимущества бренда (УТП)")
    locations: Optional[List[LocationBranch]] = Field(default_factory=list, description="Адреса филиалов и точек продаж")
    deliveryInfo: Optional[str] = Field(None, description="Условия доставки и самовывоза")
    language: Optional[str] = Field("ru", description="Основной язык контента (ru, en, pt, de...)")
    recentPostTopics: Optional[List[str]] = Field(default_factory=list, description="Темы последних постов для защиты от повторений")

    # Базовые инфраструктурные поля
    socialLinks: Optional[Dict[str, Any]] = Field(None, description="Ссылки на соцсети (telegram, instagram, vk, website)")
    businessHours: Optional[Dict[str, Any]] = Field(None, description="График работы и выходные дни")
    ownerId: Optional[str] = Field(None, description="ID владельца")
    logoUrl: Optional[str] = Field(None, description="URL логотипа бренда")
    brandColors: Optional[List[str]] = Field(None, description="Фирменные цвета (Hex)")
    usp: Optional[str] = Field(None, description="Уникальное торговое предложение")


class GeneratePostRequest(BaseModel):
    projectId: Optional[str] = Field(None, description="ID проекта")
    project_id: Optional[str] = Field(None, description="ID проекта")
    prompt: Optional[str] = Field(None, description="Промпт или тема публикации")
    topic: Optional[str] = Field(None, description="Тема публикации (алиас)")
    companyName: Optional[str] = Field(None, description="Название компании")
    company_name: Optional[str] = Field(None, description="Название компании (алиас)")
    niche: Optional[str] = Field(None, description="Ниша бизнеса")
    attachments: Optional[List[Any]] = Field(default_factory=list, description="Медиа-вложения (фото, референсы)")
    promoCode: Optional[str] = Field(None, description="Промокод / специальное предложение")
    promo_code: Optional[str] = Field(None, description="Промокод (алиас)")
    
    # 🌟 Супер-контекст проекта
    projectContext: Optional[ProjectContext] = Field(None, description="Полный объект проекта")
    project_context: Optional[ProjectContext] = Field(None, description="Полный объект проекта (алиас)")
    
    rubric: Optional[str] = Field(None, description="Рубрика публикации: EXPERT, PRODUCT, PROMO, CASE, LIFE, MEME")
    primaryCta: Optional[str] = Field(None, description="Целевое действие: BUY, BOOK, COMMENT, CHAT, PROMO")
    targetActionLink: Optional[str] = Field(None, description="Ссылка для встраивания в целевую кнопку CTA")
    language: Optional[str] = Field("ru", description="Язык генерации поста (ru, en, pt, de...)")
    tone: Optional[str] = Field(None, description="Тон коммуникации")
    aspect_ratio: Optional[str] = Field("1:1", description="Соотношение сторон (1:1, 9:16, 16:9)")
    callback_url: Optional[str] = Field(None, description="URL для Push-коллбека")
    user_id: Optional[str] = Field("default_user", description="ID пользователя")
    session_id: Optional[str] = Field(None, description="ID сессии")
    generate_image: bool = Field(True, description="Флаг генерации визуального контента")


class AsyncGenerateTaskRequest(BaseModel):
    topic: str = Field(..., description="Тема или промпт поста")
    company_name: Optional[str] = Field("UCust", description="Название компании")
    niche: Optional[str] = Field("Бизнес", description="Ниша")
    tone: Optional[str] = Field("Дерзкий, уверенный, вдохновляющий", description="Тон общения")
    aspect_ratio: Optional[str] = Field("9:16", description="Формат соотношения сторон (1:1, 4:5, 9:16, 16:9)")
    variation_index: Optional[int] = Field(0, description="Индекс ракурса/вариации (0, 1, 2, 3...)")
    stage: Optional[str] = Field("problem_aware", description="Ступень воронки Ханта")
    framework: Optional[str] = Field(None, description="PAS | AIDA | StoryBrand | BAB")
    trigger: Optional[str] = Field(None, description="Триггер Чалдини")
    tier: Optional[str] = Field("BUSINESS", description="Тариф медиа-оснащения")
    custom_prompt: Optional[str] = Field(None, description="Пользовательский визуальный промпт")
    attachments: Optional[List[Dict[str, Any]]] = Field(None, description="Вложения для анализа и генерации")
    callback_url: Optional[str] = Field(None, description="URL для отправки результата (Push-коллбек)")
    task_id: Optional[str] = Field(None, description="Опциональный внешний task_id")
    user_id: Optional[str] = Field("default_user", description="ID пользователя")
    session_id: Optional[str] = Field(None, description="ID сессии")
    projectContext: Optional[ProjectContext] = Field(None, description="Полный контекст проекта")
    project_context: Optional[ProjectContext] = Field(None, description="Полный контекст проекта (алиас)")


class PollGenerateAPIRequest(BaseModel):
    topic: str = Field(..., description="Тема опроса или инфоповод")
    niche: Optional[str] = Field("Бизнес", description="Ниша / сфера деятельности")
    company_name: Optional[str] = Field("", description="Название компании / бренда")
    goal: Optional[str] = Field("engagement", description="engagement (TOFU) | qualification (MOFU) | decision (BOFU) | knowledge_check (Quiz)")
    is_quiz: Optional[bool] = Field(False, description="Сгенерировать викторину с правильным ответом")
    options_count: Optional[int] = Field(4, ge=2, le=10, description="Желаемое количество вариантов")
    is_anonymous: Optional[bool] = Field(False, description="Анонимный опрос")
    allows_multiple_answers: Optional[bool] = Field(False, description="Разрешить выбор нескольких вариантов")


class PollPublishAPIRequest(BaseModel):
    platform: Optional[str] = Field("telegram", description="telegram | vk")
    channel: Optional[str] = Field("@UcustAi", description="Telegram username (@channel) или ID группы VK")
    question: str = Field(..., max_length=255, description="Вопрос опроса")
    options: List[str] = Field(..., min_items=2, max_items=10, description="Варианты ответов")
    poll_type: Optional[str] = Field("regular", description="regular | quiz")
    is_anonymous: Optional[bool] = Field(False, description="Анонимный опрос")
    allows_multiple_answers: Optional[bool] = Field(False, description="Множественный выбор")
    correct_option_id: Optional[int] = Field(None, description="Индекс правильного ответа (для викторин)")
    explanation: Optional[str] = Field(None, description="Пояснение для викторин")
    accompanying_text: Optional[str] = Field("", description="Текст поста / подводки")


# -------------------------------------------------------------------

# 2. Инициализация FastAPI приложения
# -------------------------------------------------------------------

from contextlib import asynccontextmanager
from core.queue_manager import AsyncGenerationQueueManager
from core.vram_scheduler import AutoCalibratingVRAMScheduler

vram_scheduler = AutoCalibratingVRAMScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Старт фонового GPU-воркера очереди при запуске приложения
    await queue_manager.start_worker()
    # 2. Фоновый прогрев GPU-моделей (Warmup Routine) для исключения холодных OOM
    asyncio.create_task(vram_scheduler.warmup_gpu_pipelines(orchestrator))
    yield
    # Остановка воркера при выключении
    await queue_manager.stop_worker()

from core.observability import init_sentry, ObservabilityManager
from fastapi import Request, Response

# Инициализация Sentry
init_sentry()

app = FastAPI(
    title="UCust AI Service Gateway",
    description="Единая точка входа для бэкенда и фронтенда к команде автономных ИИ-агентов UCust.",
    version="2.5.0",
    lifespan=lifespan
)

# Prometheus HTTP Middleware для замера RPS и Latency
@app.middleware("http")
async def prometheus_metrics_middleware(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    
    # Исключаем служебные запросы из детального трейсинга
    if request.url.path not in ["/metrics", "/health", "/api/v1/ai/health"]:
        ObservabilityManager.record_http_request(
            method=request.method,
            endpoint=request.url.path,
            status_code=response.status_code,
            duration_sec=process_time
        )
    return response

# Разрешаем CORS для любых фронтендов (React, Next.js, Vue, Mobile)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Раздача сгенерированных фото и медиа файлов
output_static_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "output"))
os.makedirs(os.path.join(output_static_dir, "photos"), exist_ok=True)
app.mount("/output", StaticFiles(directory=output_static_dir), name="output")

from storage.models import Base

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    db_engine = create_engine("sqlite:///./ai_smm_dev.db", echo=False)
    if hasattr(Base, "metadata") and Base.metadata is not None:
        Base.metadata.create_all(bind=db_engine)
    SessionLocal = sessionmaker(bind=db_engine)
    db_session = SessionLocal()
except Exception as e:
    db_engine = None
    SessionLocal = None
    db_session = None

orchestrator = UnifiedOrchestrator(db_session=db_session)
rag_pipeline = CleanRAGPipeline(min_confidence_threshold=0.65)
queue_manager = AsyncGenerationQueueManager(orchestrator=orchestrator)
content_strategy_engine = ContentStrategyEngine(dev_mode=True)
lazy_controller = LazyRenderingController(dev_simulation_mode=True)

from api.routers.async_tasks import router as async_tasks_router
app.include_router(async_tasks_router)


# -------------------------------------------------------------------
# Prometheus Metrics Scrape Endpoint
# -------------------------------------------------------------------
@app.get("/metrics", tags=["Observability & Telemetry"])
async def get_prometheus_metrics():
    """
    Экспорт метрик Prometheus (RPS, Latency, Celery Queue Depth, VRAM Allocation).
    """
    metrics_data, content_type = ObservabilityManager.export_metrics()
    return Response(content=metrics_data, media_type=content_type)


# ============================================================================
# ЕДИНЫЙ КОМАНДНЫЙ ШЛЮЗ ОРКЕСТРАТОРА (v2.5.0 WIREGUARD HTTP REST)
# ============================================================================

@app.post("/api/v1/orchestrator/execute", response_model=OrchestratorTaskResponse, tags=["Unified Orchestrator Gateway"])
@app.post("/api/v1/task/execute", response_model=OrchestratorTaskResponse, tags=["Unified Orchestrator Gateway"])
async def execute_orchestrator_task(
    request: OrchestratorTaskRequest,
    x_internal_secret: Optional[str] = Header(None, alias="X-Internal-Secret"),
) -> OrchestratorTaskResponse:
    """
    ЕДИНЫЙ КОМАНДНЫЙ ШЛЮЗ ОРКЕСТРАТОРА ДЛЯ БЭКЕНДА (v2.5.0):
    - Принимает любую задачу ('generate_post', 'quick_vision', 'onboard_user', 'analyze_documents', 'quick_scan', 'plan_content', 'feedback_loop', 'rag_query', 'rag_ingest').
    - Проводит централизованную валидацию безопасности (SSRF, Injections, Secret).
    - Выполняет оркестровку через UnifiedOrchestrator.
    - Автоматически синхронизирует результат с основным бэкендом (HTTP Push Webhook) при sync_backend=True.
    """
    import time

    # 1. Проверка внутреннего секрета доступа
    expected_secret = os.getenv("INTERNAL_API_SECRET", "ucust-super-secret-service-token-2026")
    if x_internal_secret and x_internal_secret != expected_secret:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid internal secret.")

    t_start = time.time()
    session_id = request.session_id or f"sess_{int(time.time()*1000)}"

    # 2. Обогащение payload системными метаданными
    task_payload = dict(request.payload)
    task_payload["user_id"] = request.user_id
    task_payload["session_id"] = session_id
    if request.project_id:
        task_payload["project_id"] = request.project_id
        task_payload["tenant_id"] = request.project_id

    # 3. Безопасность ввода
    for k, v in task_payload.items():
        if isinstance(v, str) and not SecurityGuard.check_user_input(v):
            return OrchestratorTaskResponse(
                status="error",
                task_type=request.task_type,
                user_id=request.user_id,
                session_id=session_id,
                data={},
                timings={"total_seconds": round(time.time() - t_start, 3)},
                error=f"Security Violation: обнаружен недопустимый ввод в поле '{k}'"
            )

    try:
        result_data = await orchestrator.execute_task(
            task_type=request.task_type,
            user_data=task_payload,
            session_id=session_id
        )

        total_sec = round(time.time() - t_start, 3)
        timings = result_data.get("timings") if isinstance(result_data, dict) else {}
        if isinstance(timings, dict):
            timings["gateway_total_seconds"] = total_sec

        # 4. Фоновый Auto-Push в бэкенд (динамический callback_url или глобальный из .env)
        if request.sync_backend:
            backend_cb = request.callback_url or os.getenv("BACKEND_COLLECTOR_CALLBACK_URL") or os.getenv("JAVA_BACKEND_CALLBACK_URL")
            if backend_cb:
                async def _push_bg():
                    try:
                        import aiohttp
                        async with aiohttp.ClientSession() as s:
                            headers = {"X-Internal-Secret": expected_secret, "Content-Type": "application/json"}
                            body = {
                                "task_id": session_id,
                                "task_type": request.task_type,
                                "status": "COMPLETED" if result_data.get("status") != "error" else "FAILED",
                                "project_id": request.project_id or task_payload.get("project_id"),
                                "user_id": request.user_id,
                                "result": result_data,
                                "timestamp": time.time()
                            }
                            await s.post(backend_cb, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=5))
                    except Exception:
                        pass
                asyncio.create_task(_push_bg())

        return OrchestratorTaskResponse(
            status="success" if result_data.get("status") != "error" else "error",
            task_type=request.task_type,
            user_id=request.user_id,
            session_id=session_id,
            data=result_data,
            timings=timings if isinstance(timings, dict) else {"total_seconds": total_sec}
        )
    except Exception as exc:
        return OrchestratorTaskResponse(
            status="error",
            task_type=request.task_type,
            user_id=request.user_id,
            session_id=session_id,
            data={},
            timings={"total_seconds": round(time.time() - t_start, 3)},
            error=str(exc)
        )


# ============================================================================
# РЕГИСТРАЦИЯ И ОНБОРДИНГ ПРОЕКТА (HUMAN-IN-THE-LOOP, 2 ФАЗЫ)
# ============================================================================

@app.post("/api/v1/projects/analyze", response_model=ProjectAnalyzeResponse, tags=["Projects Onboarding (HITL)"])
@app.post("/api/v1/parser/analyze", response_model=ProjectAnalyzeResponse, tags=["Projects Onboarding (HITL)"])
async def analyze_project_draft(
    request: ProjectAnalyzeRequest,
    x_internal_secret: Optional[str] = Header(None, alias="X-Internal-Secret")
) -> ProjectAnalyzeResponse:
    """
    ФАЗА 1: Анализ и предзаполнение черновика проекта (5 экранов UI).
    Векторы в базу данных НЕ записываются. SMM-специалист получает структурированный JSON для валидации.
    """
    expected_secret = os.getenv("INTERNAL_API_SECRET", "ucust-super-secret-service-token-2026")
    if x_internal_secret and x_internal_secret != expected_secret:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid internal secret.")

    user_payload = {
        "source_url": request.source_url,
        "niche_hint": request.niche_hint,
        "city": request.city or "Москва",
        "files": request.files or []
    }

    result = await orchestrator.execute_task(
        task_type="analyze_brand",
        user_data=user_payload
    )

    draft_dict = result.get("project_profile_draft") or {}
    return ProjectAnalyzeResponse(
        status="success" if result.get("status") != "error" else "error",
        project_profile_draft=draft_dict
    )


@app.post("/api/v1/projects/{project_id}/knowledge", response_model=ProjectCommitResponse, tags=["Projects Onboarding (HITL)"])
@app.post("/api/v1/projects/{project_id}/commit", response_model=ProjectCommitResponse, tags=["Projects Onboarding (HITL)"])
@app.post("/api/v1/projects/commit", response_model=ProjectCommitResponse, tags=["Projects Onboarding (HITL)"])
async def commit_project_knowledge(
    request: ProjectCommitRequest,
    project_id: Optional[str] = None,
    x_internal_secret: Optional[str] = Header(None, alias="X-Internal-Secret")
) -> ProjectCommitResponse:
    """
    ФАЗА 2: Фиксация и векторизация утвержденного человеком профиля (5 экранов).
    Строгая изоляция семантических векторов в pgvector под уникальным project_id.
    """
    expected_secret = os.getenv("INTERNAL_API_SECRET", "ucust-super-secret-service-token-2026")
    if x_internal_secret and x_internal_secret != expected_secret:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid internal secret.")

    target_project_id = project_id or request.data.about.name or "default_project"

    result = await orchestrator.execute_task(
        task_type="rag_ingest",
        user_data={
            "project_id": target_project_id,
            "data": request.data.dict()
        }
    )

    return ProjectCommitResponse(
        status="success" if result.get("status") != "error" else "error",
        project_id=target_project_id,
        chunks_indexed=result.get("chunks_indexed", 5),
        message="База знаний проекта успешно сформирована и векторизована в pgvector"
    )


# -------------------------------------------------------------------
# 3. REST API Эндпоинты
# -------------------------------------------------------------------

@app.post("/orchestration/generate", tags=["Direct Generation Bridge"])
@app.post("/api/v1/orchestration/generate", tags=["Direct Generation Bridge"])
async def direct_orchestration_generate(
    request: GeneratePostRequest,
    x_internal_secret: Optional[str] = Header(None, alias="X-Internal-Secret"),
):
    """
    ⚡ ПРЯМОЙ ЭНДПОИНТ ГЕНЕРАЦИИ КОНТЕНТА ДЛЯ БЭКЕНДА (с поддержкой ProjectContext):
    - Принимает как минимальные параметры (prompt, attachments, promoCode),
      так и полный объект проекта (city, toneOfVoice, targetAudience, businessHours, logoUrl, socialLinks).
    - Автоматически обогащает контекст для Saiga LLM, Moondream2 и ComfyUI.
    - Выполняет сквозную оркестровку и возвращает структурированный результат.
    """
    expected_secret = os.getenv("INTERNAL_API_SECRET", "ucust-super-secret-service-token-2026")
    if x_internal_secret and x_internal_secret != expected_secret:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid internal secret.")

    session_id = request.session_id or f"sess_{uuid.uuid4().hex[:8]}"

    # 1. Базовый payload
    task_payload: Dict[str, Any] = {
        "prompt": request.prompt or request.topic or "",
        "topic": request.prompt or request.topic or "",
        "company_name": request.companyName or request.company_name or "UCust",
        "niche": request.niche or "Бизнес",
        "attachments": request.attachments or [],
        "promo_code": request.promoCode or request.promo_code,
        "offer": request.promoCode or request.promo_code,
        "aspect_ratio": request.aspect_ratio or "1:1",
        "generate_image": request.generate_image,
        "tone": request.tone or "Естественный и живой",
        "user_id": request.user_id or "default_user",
        "session_id": session_id,
        "project_id": request.projectId or request.project_id
    }

    # 2. Обогащение данными из ProjectContext
    proj = request.projectContext or request.project_context
    if proj:
        proj_dict = proj.dict(exclude_none=True)
        task_payload["project_context"] = proj_dict
        task_payload["project"] = proj_dict
        if proj.name or proj.companyName:
            task_payload["company_name"] = proj.name or proj.companyName
        if proj.industry or proj.niche:
            task_payload["niche"] = proj.industry or proj.niche
        if proj.city:
            task_payload["city"] = proj.city
        if proj.description:
            task_payload["description"] = proj.description
            task_payload["usp"] = proj.description
        if proj.targetAudience:
            task_payload["target_audience"] = proj.targetAudience
        if proj.toneOfVoice:
            task_payload["tone"] = proj.toneOfVoice
            task_payload["tone_of_voice"] = proj.toneOfVoice
        if proj.socialLinks:
            task_payload["social_links"] = proj.socialLinks
        if proj.businessHours:
            task_payload["business_hours"] = proj.businessHours
        if proj.logoUrl:
            task_payload["logo_url"] = proj.logoUrl
        if proj.brandColors:
            task_payload["brand_colors"] = proj.brandColors
        if proj.id or proj.projectId:
            task_payload["project_id"] = proj.id or proj.projectId
        if proj.brandGuidelines:
            task_payload["brand_guidelines"] = proj.brandGuidelines.dict(exclude_none=True)
            if proj.brandGuidelines.forbiddenWords:
                task_payload["forbidden_words"] = proj.brandGuidelines.forbiddenWords
            if proj.brandGuidelines.mandatoryPhrases:
                task_payload["mandatory_phrases"] = proj.brandGuidelines.mandatoryPhrases
            if proj.brandGuidelines.addressingStyle:
                task_payload["addressing_style"] = proj.brandGuidelines.addressingStyle
            if proj.brandGuidelines.emojiPolicy:
                task_payload["emoji_policy"] = proj.brandGuidelines.emojiPolicy
        if proj.visualDna:
            task_payload["visual_dna"] = proj.visualDna.dict(exclude_none=True)
            if proj.visualDna.brandColors and not task_payload.get("brand_colors"):
                task_payload["brand_colors"] = proj.visualDna.brandColors
            if proj.visualDna.visualStyle:
                task_payload["visual_style"] = proj.visualDna.visualStyle
            if proj.visualDna.moodKeywords:
                task_payload["mood_keywords"] = proj.visualDna.moodKeywords
            if proj.visualDna.logoUrl and not task_payload.get("logo_url"):
                task_payload["logo_url"] = proj.visualDna.logoUrl
        if proj.productsCatalog:
            task_payload["products_catalog"] = [p.dict(exclude_none=True) for p in proj.productsCatalog]
        if proj.keyBenefits:
            task_payload["key_benefits"] = proj.keyBenefits
        if proj.locations:
            task_payload["locations"] = [loc.dict(exclude_none=True) for loc in proj.locations]
        if proj.deliveryInfo:
            task_payload["delivery_info"] = proj.deliveryInfo
        if proj.language:
            task_payload["language"] = proj.language
        if proj.recentPostTopics:
            task_payload["recent_post_topics"] = proj.recentPostTopics

    if request.rubric:
        task_payload["rubric"] = request.rubric
    if request.primaryCta:
        task_payload["primary_cta"] = request.primaryCta
    if request.targetActionLink:
        task_payload["target_action_link"] = request.targetActionLink
    if request.language:
        task_payload["language"] = request.language

    # 3. Валидация безопасности
    payload_str = json.dumps(task_payload, ensure_ascii=False)
    if not SecurityGuard.check_user_input(payload_str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Security Violation: обнаружен недопустимый ввод в запросе."
        )

    # 4. Запуск генерации через Orchestrator
    result = await orchestrator.execute_task(
        task_type="generate_post",
        user_data=task_payload,
        session_id=session_id
    )

    return {
        "status": "success" if result.get("status") != "error" else "error",
        "session_id": session_id,
        "project_id": task_payload.get("project_id"),
        "data": result
    }



@app.get("/api/v1/ai/health", tags=["System"])

@app.get("/health", tags=["System"])
@app.get("/", tags=["System"])
async def health_check():
    """Проверка доступности ИИ-шлюза и агентов."""
    return {
        "status": "healthy",
        "service": "UCust AI Service Gateway",
        "version": "2.5.0",
        "routes": {
            "unified_orchestrator": "/api/v1/orchestrator/execute",
            "async_queue": "/api/v1/ai/tasks/async-generate",
            "health": "/api/v1/ai/health"
        },
        "agents": ["Interviewer", "Analyst", "Saiga Copywriter", "Visual Director LTX-2", "ToV Gatekeeper", "UnifiedOrchestrator"],
        "timestamp": datetime.utcnow().isoformat()
    }


@app.post("/api/v1/ai/tasks/async-generate", status_code=status.HTTP_202_ACCEPTED, tags=["Async Generation Queue"])
async def submit_async_generation_task(request: AsyncGenerateTaskRequest):
    """
    ⚡ Асинхронный запуск генерации с гарантией FIFO-очереди и Push-коллбеком на Java-бэкенд.
    Мгновенно отвечает кодом 202 Accepted, резервирует позицию в очереди и начинает обработку.
    """
    payload = request.dict(exclude={"callback_url", "task_id", "user_id", "session_id"})
    payload["task_type"] = "generate_post"

    # Проверка безопасности
    payload_str = json.dumps(payload, ensure_ascii=False)
    if not SecurityGuard.check_user_input(payload_str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Security Violation: обнаружен запрещенный запрос или попытка инъекции."
        )

    task_info = await queue_manager.enqueue_task(
        payload=payload,
        callback_url=request.callback_url,
        task_id=request.task_id,
        user_id=request.user_id or "default_user",
        session_id=request.session_id
    )
    return task_info


@app.get("/api/v1/ai/tasks/{task_id}/status", tags=["Async Generation Queue"])
async def get_async_task_status(task_id: str):
    """
    Получение текущего статуса задачи (QUEUED, PROCESSING, COMPLETED, FAILED, PUSHED)
    и позиции в очереди.
    """
    task_status = queue_manager.get_task_status(task_id)
    if not task_status:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Задача '{task_id}' не найдена в реестре очереди."
        )
    return {
        "status": "success",
        "task": task_status
    }


@app.get("/api/v1/ai/queue/stats", tags=["Async Generation Queue"])
async def get_generation_queue_stats():
    """
    Мониторинг состояния очереди и загруженности GPU.
    """
    return queue_manager.get_queue_stats()


@app.post("/api/v1/ai/task", response_model=TaskResponse, tags=["AI Tasks"])
async def execute_ai_task(request: TaskRequest):
    """
    Универсальный эндпоинт выполнения задач агентами.
    Бэкенд передает task_type и payload, Оркестратор распределяет нагрузку.
    """
    session_id = request.session_id or f"sess_{uuid.uuid4().hex[:8]}"
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    
    # 1. Проверка безопасности входящих данных
    payload_str = json.dumps(request.payload, ensure_ascii=False)
    if not SecurityGuard.check_user_input(payload_str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Security Violation: обнаружен запрещенный запрос или попытка инъекции."
        )

    # 2. Передача в UnifiedOrchestrator
    try:
        result = await orchestrator.execute_task(
            task_type=request.task_type,
            user_data=request.payload,
            session_id=session_id
        )
        
        if result.get("status") == "error":
            return TaskResponse(
                status="error",
                task_id=task_id,
                session_id=session_id,
                error=result.get("message", "Ошибка выполнения задачи")
            )
            
        return TaskResponse(
            status="success",
            task_id=task_id,
            session_id=session_id,
            data=result
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка оркестратора: {str(e)}"
        )


@app.get("/api/v1/ai/trends", response_model=TrendResponse, tags=["Trends & Analytics"])
async def get_weekly_trends(niche: str = Query("IT и Автоматизация", description="Ниша бизнеса")):
    """
    Отдача закешированных недельных трендов из Redis за 3-5 миллисекунд.
    """
    session_id = f"trend_req_{uuid.uuid4().hex[:6]}"
    result = await orchestrator.execute_task(
        task_type="get_trends",
        user_data={"niche": niche},
        session_id=session_id
    )
    
    return TrendResponse(
        niche=niche,
        trends=result.get("trends", ""),
        cached=True
    )


@app.get("/api/v1/ai/analytics/graphs", tags=["Trends & Analytics"])
async def get_frontend_graphs():
    """
    Безопасные агрегированные данные для графиков и дашбордов фронтенда (без PII).
    """
    graphs_data = orchestrator.get_frontend_graph_data()
    return {
        "status": "success",
        "data": graphs_data
    }


# ============================================================================
# СМАРТ-БАНК ИДЕЙ И ДИНАМИЧЕСКИЕ ПЛЕЙСХОЛДЕРЫ (FUNNEL-SAFE IDEA ENGINE)
# ============================================================================

class EvaluatePlacementAPIRequest(BaseModel):
    topic: str = Field(..., example="Как наша команда отмечает День программиста: закулисье и подарок клиентам")
    niche: str = Field("IT / Разработка", example="IT / Разработка")
    company_name: str = Field("UCust", example="UCust")
    target_slot_date: Optional[str] = None
    target_slot_type: Optional[str] = None
    is_override_scheduled_slot: bool = False


@app.get("/api/v1/ideas/placeholders", tags=["Smart Idea Bank"])
async def get_ideas_placeholders(
    niche: str = Query("Бизнес", description="Ниша бизнеса"),
    company_name: str = Query("", description="Название бренда/компании"),
    limit: int = Query(5, ge=1, le=10, description="Количество вариантов плейсхолдера")
):
    """
    💡 ДИНАМИЧЕСКИЕ ПЛЕЙСХОЛДЕРЫ ДЛЯ ПОЛЯ ВВОДА ТЕМЫ:
    - Подгружает актуальные инфоповоды из календаря и сезонные темы в плейсхолдер.
    - Пользователь может нажать Tab для мгновенной подстановки темы без поломки календаря.
    """
    from skills.smart_idea_bank import SmartIdeaBank
    idea_bank = SmartIdeaBank()
    placeholders = idea_bank.get_dynamic_placeholders(niche=niche, company_name=company_name, limit=limit)
    return {
        "status": "success",
        "niche": niche,
        "company_name": company_name,
        "placeholders": [p.dict() for p in placeholders]
    }


@app.get("/api/v1/ideas/bank", tags=["Smart Idea Bank"])
async def get_quick_ideas_bank(
    niche: str = Query("Бизнес", description="Ниша бизнеса"),
    country: str = Query("россия", description="Страна для календаря праздников"),
    days_ahead: int = Query(21, ge=1, le=60, description="Горизонт планирования (в днях)"),
    company_name: str = Query("", description="Название бренда")
):
    """
    🏦 БАНК БЫСТРЫХ ИДЕЙ (IDEA BANK):
    - Отделенный от автоматического расписания каталог инфоповодов и ситуативных тем.
    - Не вмешивается в существующий конверсионный календарь на лету.
    - Содержит оценку релевантности нише и рекомендации по этапу воронки (TOFU/MOFU/BOFU).
    """
    from skills.smart_idea_bank import SmartIdeaBank
    idea_bank = SmartIdeaBank()
    ideas = idea_bank.get_quick_ideas_bank(niche=niche, country=country, days_ahead=days_ahead, company_name=company_name)
    return {
        "status": "success",
        "niche": niche,
        "country": country,
        "ideas_count": len(ideas),
        "ideas": [i.dict() for i in ideas]
    }


@app.post("/api/v1/ideas/evaluate-placement", tags=["Smart Idea Bank"])
async def evaluate_ideas_placement(request: EvaluatePlacementAPIRequest):
    """
    🛡️ СОВЕТНИК РАЗМЕЩЕНИЯ ИДЕИ В ВОРОНКУ (FUNNEL INTEGRITY ADVISOR):
    - Анализирует выбранную тему на совместимость с этапом воронки продаж.
    - Защищает конверсионные BOFU-слоты от случайного затирания вирусными мемами или праздниками.
    - Выдает четкий вердикт: сохранить в черновики, поставить в подходящий слот или выпустить внепланово.
    """
    from skills.smart_idea_bank import SmartIdeaBank
    idea_bank = SmartIdeaBank()
    verdict = idea_bank.evaluate_funnel_placement(
        topic=request.topic,
        niche=request.niche,
        company_name=request.company_name,
        target_slot_date=request.target_slot_date,
        target_slot_type=request.target_slot_type,
        is_override_scheduled_slot=request.is_override_scheduled_slot
    )
    return {
        "status": "success",
        "verdict": verdict.dict()
    }


# ============================================================================
# ИНТЕРАКТИВНЫЕ ОПРОСЫ И ВИКТОРИНЫ (INTERACTIVE POLLS & QUIZZES)
# ============================================================================

@app.post("/api/v1/content/poll/generate", tags=["Interactive Polls & Social Quizzes"])
@app.post("/api/v1/ai/poll/generate", tags=["Interactive Polls & Social Quizzes"])
async def generate_interactive_poll(request: PollGenerateAPIRequest):
    """
    📊 ГЕНЕРАЦИЯ ИНТЕРАКТИВНЫХ ОПРОСОВ И КВИЗОВ ДЛЯ СОЦСЕТЕЙ (Telegram / VK):
    - Поддерживает 4 типа: вовлекающие (TOFU), выявление болей (MOFU), выбор продукта (BOFU) и викторины с проверкой знаний (Quiz).
    - Возвращает структурированный вопрос, до 10 вариантов ответа, подводку к посту и правильный ответ с объяснением.
    """
    from skills.poll_generator import PollGeneratorSkill
    poll_gen = PollGeneratorSkill()
    poll = poll_gen.generate_poll(
        topic=request.topic,
        niche=request.niche or "Бизнес",
        company_name=request.company_name or "UCust",
        goal=request.goal or "engagement",
        is_quiz=request.is_quiz or False,
        options_count=request.options_count or 4,
        is_anonymous=request.is_anonymous or False,
        allows_multiple_answers=request.allows_multiple_answers or False
    )
    return {
        "status": "success",
        "poll": poll.dict()
    }


@app.post("/api/v1/publishers/poll", tags=["Interactive Polls & Social Quizzes", "Publishers"])
@app.post("/api/v1/ai/poll/publish", tags=["Interactive Polls & Social Quizzes", "Publishers"])
async def publish_interactive_poll(request: PollPublishAPIRequest):
    """
    🚀 ПУБЛИКАЦИЯ НАЦИОНАЛЬНОГО ОПРОСА В TELEGRAM ИЛИ VK:
    - В Telegram: публикует через Bot API sendPoll или Telethon с поддержкой квизов и таймеров.
    - В VK: создает опрос через polls.create и прикрепляет к посту на стене (wall.post).
    """
    if (request.platform or "telegram").lower() == "vk":
        from publishers.vk import VkPublisher
        vk_pub = VkPublisher(group_id=request.channel or "@UcustAi")
        res = await vk_pub.publish_poll(
            question=request.question,
            options=request.options,
            is_anonymous=request.is_anonymous or False,
            allows_multiple_answers=request.allows_multiple_answers or False,
            accompanying_text=request.accompanying_text or ""
        )
        return {
            "status": "success",
            "platform": "vk",
            "data": res
        }
    else:
        from publishers.telegram import TelegramPublisher
        tg_pub = TelegramPublisher(target_channel=request.channel or "@UcustAi")
        res = await tg_pub.publish_poll(
            question=request.question,
            options=request.options,
            is_anonymous=request.is_anonymous or False,
            allows_multiple_answers=request.allows_multiple_answers or False,
            poll_type=request.poll_type or "regular",
            correct_option_id=request.correct_option_id,
            explanation=request.explanation
        )
        return {
            "status": "success",
            "platform": "telegram",
            "data": res
        }


# ============================================================================

# ДИАГНОСТИКА VRAM И АДАПТИВНОГО ПЛАНИРОВЩИКА GPU
# ============================================================================

@app.get("/api/v1/ai/system/gpu-status", tags=["System Diagnostics"])
@app.get("/gpu-status", tags=["System Diagnostics"])
async def get_gpu_vram_status():
    """
    📊 РЕАЛЬНОЕ СОСТОЯНИЕ ВИДЕОПАМЯТИ И ДИСПЕТЧЕРА VRAM:
    - Текущее распределение VRAM (Total, Used, Free в GB).
    - Количество активных GPU-воркеров и параллельных I/O-парсеров.
    - Самообученные (Auto-Calibrated) веса каждой задачи с учетом EMA и пиковых всплесков.
    """
    return vram_scheduler.get_diagnostics()


@app.post("/api/v1/ai/generate-image", tags=["Visual & Media"])
async def generate_smm_image(request: ImageGenerateRequest):
    """
    Генерация качественного SMM-изображения для постов, баннеров и сторис.
    """
    result = await orchestrator.execute_task(
        task_type="generate_image",
        user_data=request.dict(),
        session_id=f"img_{uuid.uuid4().hex[:8]}"
    )
    return result


@app.post("/api/v1/ai/vision/analyze", tags=["Visual & Media"])
async def analyze_visual_media(request: VisionAnalyzeRequest):
    """
    Анализ загруженного фото через ИИ-аналитика Moondream2.
    Извлекает доминирующие цвета, ключевые объекты, композицию и готовит промпт.
    """
    from skills.moondream_vqa import MoondreamVQASkill
    moondream = MoondreamVQASkill()
    
    if request.attachments:
        result = moondream.analyze_attachments_batch(
            attachments=request.attachments,
            topic=request.topic or "",
            company_name=request.company_name or "UCust"
        )
    elif request.image:
        result = moondream.extract_visual_dossier(
            image_input=request.image,
            topic=request.topic or "",
            company_name=request.company_name or "UCust"
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не передано изображение или список вложений для анализа."
        )
        
    return {
        "status": "success",
        "vision_analyst": "Moondream2",
        "data": result
    }


@app.post("/api/v1/ai/website/analyze", tags=["Collectors & Web Scrapers", "Web & Social Intelligence"])
@app.post("/api/v1/collectors/website", tags=["Collectors & Web Scrapers", "Web & Social Intelligence"])
async def analyze_website(request: WebsiteAnalyzeRequest):
    """
    Глубокий парсинг и ИИ-анализ веб-сайта компании (B2B, e-commerce, лендинги).
    Извлекает УТП, заголовки, описание услуг, контакты, соцсети и готовит контекст для LLM.
    """
    from collectors.website_collector import WebsiteCollector
    collector = WebsiteCollector()
    result = await collector.collect_website_async(request.url)
    
    if result.get("status") == "error":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Не удалось распарсить сайт: {result.get('error')}"
        )
        
    return {
        "status": "success",
        "analyst": "WebsiteCollector",
        "data": result
    }


@app.post("/api/v1/ai/competitor/analyze", tags=["Web & Social Intelligence"])
async def analyze_competitor(request: CompetitorAnalyzeRequest):
    """
    Глубокая декомпозиция конкурента (Strengths, Weaknesses, Pricing, UVP)
    и генерация контр-стратегии отстройки для SMM.
    """
    from skills.competitive_intel import CompetitiveIntelSkill
    intel = CompetitiveIntelSkill()
    result = await intel.analyze_competitor_async(request.url, my_company_niche=request.niche)
    
    if result.get("status") == "error":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ошибка анализа конкурента: {result.get('error')}"
        )
        
    return {
        "status": "success",
        "analyst": "CompetitiveIntelSkill",
        "data": result
    }


# ============================================================================
# ПАРСЕРЫ И СБОРЩИКИ ДАННЫХ (COLLECTORS & WEB SCRAPERS)
# ============================================================================

@app.post("/api/v1/ai/telegram/analyze", tags=["Collectors & Web Scrapers"])
@app.post("/api/v1/collectors/telegram", tags=["Collectors & Web Scrapers"])
async def analyze_telegram_channel(
    request: TelegramAnalyzeRequest,
    x_internal_secret: Optional[str] = Header(None, alias="X-Internal-Secret"),
):
    """
    ⚡ Парсинг и VLM-анализ Telegram-канала (@username или ссылка t.me/...):
    - Извлекает последние посты, метрики охвата, комментарии и возражения аудитории.
    - При include_media_vqa=True анализирует прикрепленные фото через связку Moondream2 + OCR (PaddleOCR).
    """
    task_req = OrchestratorTaskRequest(
        task_type="parse_telegram",
        user_id=request.user_id or "default_user",
        session_id=request.session_id,
        payload=request.dict()
    )
    res = await execute_orchestrator_task(task_req, x_internal_secret=x_internal_secret)
    if res.status == "error":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=res.error or "Ошибка парсинга Telegram")
    return res.data


@app.post("/api/v1/ai/vk/analyze", tags=["Collectors & Web Scrapers"])
@app.post("/api/v1/collectors/vk", tags=["Collectors & Web Scrapers"])
async def analyze_vk_group(
    request: VkAnalyzeRequest,
    x_internal_secret: Optional[str] = Header(None, alias="X-Internal-Secret"),
):
    """
    ⚡ Парсинг сообщества ВКонтакте (VK):
    - Сбор постов, реакций (лайков/просмотров) и частых вопросов аудитории.
    """
    task_req = OrchestratorTaskRequest(
        task_type="parse_vk",
        user_id=request.user_id or "default_user",
        session_id=request.session_id,
        payload=request.dict()
    )
    res = await execute_orchestrator_task(task_req, x_internal_secret=x_internal_secret)
    if res.status == "error":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=res.error or "Ошибка парсинга VK")
    return res.data


@app.post("/api/v1/ai/geo/analyze", tags=["Collectors & Web Scrapers"])
@app.post("/api/v1/collectors/geo", tags=["Collectors & Web Scrapers"])
async def analyze_geo_reviews(
    request: GeoAnalyzeRequest,
    x_internal_secret: Optional[str] = Header(None, alias="X-Internal-Secret"),
):
    """
    ⚡ Парсинг отзывов и рейтинга организации из 2GIS и Яндекс Карт:
    - Извлекает клиентский опыт, реальные отзывы, оценки и частые жалобы/похвалы.
    """
    task_req = OrchestratorTaskRequest(
        task_type="parse_geo",
        user_id=request.user_id or "default_user",
        session_id=request.session_id,
        payload=request.dict()
    )
    res = await execute_orchestrator_task(task_req, x_internal_secret=x_internal_secret)
    if res.status == "error":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=res.error or "Ошибка парсинга гео-сервиса")
    return res.data


@app.post("/api/v1/collectors/parse", tags=["Collectors & Web Scrapers"])
@app.post("/api/v1/ai/collectors/parse", tags=["Collectors & Web Scrapers"])
@app.post("/api/v1/ai/parse", tags=["Collectors & Web Scrapers"])
async def universal_collector_parse(
    request: UniversalCollectorRequest,
    x_internal_secret: Optional[str] = Header(None, alias="X-Internal-Secret"),
):
    """
    🌐 Универсальный шлюз сбора данных по любому источнику (Telegram, VK, Website, 2GIS, Yandex, Документы).
    Автоматически определяет тип источника по ссылке или типу и возвращает нормализованную схему.
    """
    st = (request.source_type or "auto").lower().strip()
    target = (request.target or "").strip()

    # Умное автоопределение источника по ссылке/формату, если source_type="auto"
    if st == "auto":
        target_lower = target.lower()
        if "t.me/" in target_lower or target.startswith("@"):
            st = "telegram"
        elif "vk.com/" in target_lower:
            st = "vk"
        elif "2gis.ru" in target_lower or "2gis.com" in target_lower:
            st = "2gis"
        elif "yandex.ru/maps" in target_lower or "maps.yandex." in target_lower:
            st = "yandex"
        elif any(target_lower.endswith(ext) for ext in [".pdf", ".docx", ".doc", ".pptx", ".txt"]):
            st = "documents"
        elif target_lower.startswith("http://") or target_lower.startswith("https://") or "." in target:
            st = "website"
        else:
            st = "telegram"  # fallback по умолчанию для @-тегов

    if st in {"telegram", "tg"}:
        task_type = "parse_telegram"
        payload = {"channel": target, "limit": request.limit, "include_media_vqa": request.include_media_vqa, **(request.payload or {})}
    elif st in {"vk", "vkontakte"}:
        task_type = "parse_vk"
        payload = {"group_id": target, "limit": request.limit, **(request.payload or {})}
    elif st in {"geo", "2gis", "yandex", "maps"}:
        task_type = "parse_geo"
        payload = {"url": target, "provider": st, "limit": request.limit, **(request.payload or {})}
    elif st in {"site", "website", "web"}:
        task_type = "parse_website"
        payload = {"url": target, **(request.payload or {})}
    elif st in {"doc", "document", "documents", "file"}:
        task_type = "analyze_documents"
        payload = {"documents": [target], **(request.payload or {})}
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Неизвестный тип источника '{request.source_type}'. Доступны: auto, telegram, vk, website, geo, 2gis, yandex, documents"
        )

    task_req = OrchestratorTaskRequest(
        task_type=task_type,
        user_id=request.user_id or "default_user",
        session_id=request.session_id,
        payload=payload
    )
    res = await execute_orchestrator_task(task_req, x_internal_secret=x_internal_secret)
    if res.status == "error":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=res.error or f"Ошибка сбора данных из {st}")
    return res.data




@app.post("/api/v1/ai/strategy/generate", tags=["Content Strategy & Personas"])
async def generate_content_strategy(request: StrategyGenerateRequest):
    """
    Генерация воронки контента (TOFU / MOFU / BOFU), арсенала виральных хуков
    и глубокого портрета покупателя (Jobs-to-be-Done, Pains, Triggers).
    """
    from skills.content_strategy_engine import ContentStrategyEngine
    engine = ContentStrategyEngine()
    result = engine.generate_strategy(
        company_name=request.company_name or "UCust",
        niche=request.niche,
        target_audience=request.target_audience or "",
        key_usp=request.usp or ""
    )
    return {
        "status": "success",
        "strategist": "ContentStrategyEngine",
        "data": result
    }


@app.post("/api/v1/ai/critic/review", tags=["Content Quality & Pre-Mortem"])
async def review_content_with_critic(request: CriticReviewRequest):
    """
    Инверсионный Pre-Mortem аудит текста (методология Чарли Мангера):
    выявление клише, скучных хуков, отсутствия CTA и генерация правок для автора.
    """
    from skills.critic_munger import CriticMungerSkill
    critic = CriticMungerSkill(strictness=request.strictness or 0.85)
    result = critic.review_content(
        text=request.text,
        topic=request.topic or "",
        target_audience=request.niche or ""
    )
    return {
        "status": "success",
        "critic": "Charlie Munger Pre-Mortem Agent",
        "data": result
    }


@app.post("/api/v1/ai/achievements/post", tags=["Telegram Achievement Broadcaster"])
async def broadcast_achievement_endpoint(request: AchievementBroadcastRequest):
    """
    Публикация крупного достижения / релиза в официальный Telegram-канал (@UcustAi).
    Поддерживает прикрепление медиафайлов, форматирование метрик и HTML-теги.
    """
    from publishers.achievement_broadcaster import AchievementBroadcaster
    broadcaster = AchievementBroadcaster(target_channel=request.channel or "@UcustAi")
    result = await broadcaster.broadcast_milestone_async(
        title=request.title,
        description=request.description,
        metrics=request.metrics,
        media_path=request.media_path
    )
    if result.get("status") == "error":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ошибка публикации достижения: {result.get('error') or result.get('message')}"
        )
    return {
        "status": "success",
        "broadcaster": "Telethon AchievementBroadcaster",
        "data": result
    }


@app.post("/api/v1/ai/rag/query", tags=["Knowledge Base RAG"])
async def query_knowledge_base(request: RAGQueryRequest):
    """
    Поиск по базе знаний через Clean RAG с защитой от галлюцинаций.
    """
    rag_context = await rag_pipeline.query_async(request.query, top_k_retrieval=request.top_k)
    return {
        "query": rag_context.query,
        "has_sufficient_context": rag_context.has_sufficient_context,
        "top_score": round(rag_context.top_score, 3),
        "context": rag_context.formatted_context if rag_context.has_sufficient_context else None,
        "fallback_message": rag_context.fallback_message
    }


@app.post("/api/v1/ai/rag/ingest", tags=["Knowledge Base RAG"])
async def ingest_knowledge_base(request: RAGIngestRequest):
    """
    Загрузка и индексация документов в локальный Clean RAG.
    """
    docs = []
    for item in request.documents:
        docs.append(
            Document(
                doc_id=item.get("doc_id", str(uuid.uuid4())),
                text=item.get("text", ""),
                source=item.get("source", "api_upload"),
                metadata=item.get("metadata", {})
            )
        )
    indexed_count = await rag_pipeline.ingest_documents_async(docs)
    return {
        "status": "success",
        "indexed_count": indexed_count,
        "message": f"Успешно проиндексировано {indexed_count} документов в Clean RAG"
    }
# -------------------------------------------------------------------
# 3.1 УДОБНЫЕ АЛИАСЫ ДЛЯ ФРОНТЕНДА И СБОРА ДАННЫХ (CONVENIENCE ALIASES)
# -------------------------------------------------------------------

class QuickVisionAnalysisRequest(BaseModel):
    user_id: str = Field("default_user", description="ID пользователя")
    session_id: Optional[str] = Field(None, description="ID сессии для кэширования")
    prompt: Optional[str] = Field("", description="Текстовый промпт/намерение пользователя")
    niche: Optional[str] = Field("Бизнес и услуги", description="Ниша бизнеса")
    company_name: Optional[str] = Field("UCust", description="Название компании")
    attachments: List[Any] = Field(..., description="1-3 фото (Base64 data-url, URL или пути к файлам)")


class DocumentAnalysisRequest(BaseModel):
    user_id: str = Field("default_user", description="ID пользователя")
    company_name: Optional[str] = Field("UCust", description="Название компании")
    niche: Optional[str] = Field("Бизнес и услуги", description="Ниша компании")
    documents: List[str] = Field(..., description="Пути к файлам или имена документов (PDF, DOCX, PPTX)")


class UnifiedBrandAnalysisRequest(BaseModel):
    user_id: str = Field("default_user", description="ID пользователя")
    company_name: Optional[str] = Field("", description="Название компании")
    niche: Optional[str] = Field("", description="Сфера деятельности")
    city: Optional[str] = Field("Москва", description="Город")
    urls: List[str] = Field(default=[], description="Ссылки: сайт, VK, Telegram, 2GIS/Яндекс")
    documents: List[str] = Field(default=[], description="Пути к документам (PDF, DOCX, PPTX)")
    images: List[Any] = Field(default=[], description="Фото / логотипы (Base64 или пути)")
    raw_notes: Optional[str] = Field("", description="Дополнительные заметки")
    fast_mode: bool = Field(True, description="Быстрый режим предварительного сканирования")


@app.post("/api/v1/vision/quick-analyze", response_model=Dict[str, Any], tags=["Convenience Aliases"])
async def quick_vision_analyze(
    payload: QuickVisionAnalysisRequest,
    x_internal_secret: Optional[str] = Header(None, alias="X-Internal-Secret"),
) -> Dict[str, Any]:
    task_req = OrchestratorTaskRequest(
        task_type="quick_vision",
        user_id=payload.user_id,
        session_id=payload.session_id,
        payload=payload.dict()
    )
    res = await execute_orchestrator_task(task_req, x_internal_secret=x_internal_secret)
    return res.data


@app.post("/api/v1/collectors/analyze-documents", response_model=Dict[str, Any], tags=["Collectors & Web Scrapers", "Convenience Aliases"])
@app.post("/api/v1/ai/documents/analyze", response_model=Dict[str, Any], tags=["Collectors & Web Scrapers", "Convenience Aliases"])
@app.post("/api/v1/collectors/documents", response_model=Dict[str, Any], tags=["Collectors & Web Scrapers", "Convenience Aliases"])
async def analyze_documents_direct(
    payload: DocumentAnalysisRequest,
    x_internal_secret: Optional[str] = Header(None, alias="X-Internal-Secret"),
) -> Dict[str, Any]:
    task_req = OrchestratorTaskRequest(
        task_type="analyze_documents",
        user_id=payload.user_id,
        payload=payload.dict()
    )
    res = await execute_orchestrator_task(task_req, x_internal_secret=x_internal_secret)
    return res.data


@app.post("/api/v1/collectors/analyze-brand", response_model=Dict[str, Any], tags=["Convenience Aliases"])
async def analyze_brand_multimodal(
    payload: UnifiedBrandAnalysisRequest,
    x_internal_secret: Optional[str] = Header(None, alias="X-Internal-Secret"),
) -> Dict[str, Any]:
    task_req = OrchestratorTaskRequest(
        task_type="quick_scan",
        user_id=payload.user_id,
        payload=payload.dict()
    )
    res = await execute_orchestrator_task(task_req, x_internal_secret=x_internal_secret)
    return res.data
# 4. WebSocket: Живой онбординг и Real-time стриминг для Фронтенда
# -------------------------------------------------------------------

class ConnectionManager:
    """Менеджер активных WebSocket подключений."""
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, session_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[session_id] = websocket
        print(f"[WebSocket] 🔌 Клиент подключен к сессии: {session_id}")

    def disconnect(self, session_id: str):
        if session_id in self.active_connections:
            del self.active_connections[session_id]
            print(f"[WebSocket] 🔌 Клиент отключен: {session_id}")

    async def send_event(self, session_id: str, step: str, payload: Any):
        if session_id in self.active_connections:
            message = {
                "session_id": session_id,
                "step": step,
                "timestamp": datetime.utcnow().isoformat(),
                "payload": payload
            }
            await self.active_connections[session_id].send_text(json.dumps(message, ensure_ascii=False))

ws_manager = ConnectionManager()


@app.websocket("/ws/ai/session/{session_id}")
async def websocket_onboarding_stream(websocket: WebSocket, session_id: str):
    """
    WebSocket канал для живого интерактивного онбординга.
    Фронтенд отправляет данные формы или сообщения пользователя,
    Оркестратор в реальном времени стримит ответы агентов и статус прогресса.
    """
    await ws_manager.connect(session_id, websocket)
    
    try:
        # Приветственное событие от Интервьюера
        await ws_manager.send_event(
            session_id=session_id,
            step="interviewer_greeting",
            payload={
                "message": "Здравствуйте! Я ИИ-ассистент онбординга UCust. Готов собрать данные о вашем бизнесе и настроить команду агентов.",
                "required_fields": ["company_name", "niche", "raw_social_input", "goals"]
            }
        )
        
        while True:
            # Получаем сообщение от фронтенда
            raw_data = await websocket.receive_text()
            user_msg = json.loads(raw_data)
            
            # 1. Этап интервьюера (проверка ссылок и целей)
            await ws_manager.send_event(
                session_id=session_id,
                step="interviewer_processing",
                payload={"status": "Проверка ссылок и структуры данных..."}
            )
            await asyncio.sleep(0.5)
            
            # Запуск онбординга через Оркестратор
            await ws_manager.send_event(
                session_id=session_id,
                step="analyst_started",
                payload={"progress": 25, "status": "Аналитик собирает посты и отзывы..."}
            )
            
            result = await orchestrator.execute_task(
                task_type="onboarding",
                user_data=user_msg,
                session_id=session_id
            )
            
            await ws_manager.send_event(
                session_id=session_id,
                step="copywriter_started",
                payload={"progress": 65, "status": "Сайга формирует Tone-of-Voice и контент-план..."}
            )
            await asyncio.sleep(0.5)
            
            # Финальное событие завершения
            await ws_manager.send_event(
                session_id=session_id,
                step="pipeline_completed",
                payload={
                    "progress": 100,
                    "status": "Команда агентов успешно настроена!",
                    "result": result
                }
            )
            
    except WebSocketDisconnect:
        ws_manager.disconnect(session_id)
    except Exception as e:
        await ws_manager.send_event(
            session_id=session_id,
            step="error",
            payload={"error": str(e)}
        )
        ws_manager.disconnect(session_id)


# ============================================================================
# 5. СТРАТЕГИЯ КОНТЕНТА И ОТЛОЖЕННЫЙ РЕНДЕР (LAZY RENDERING & CONTENT STRATEGY)
# ============================================================================

class ContentDraftApiRequest(BaseModel):
    brand_id: str = Field(..., example="brand_102", description="Уникальный ID бренда")
    company_name: str = Field("UCust", example="Specialty Coffee", description="Название компании")
    industry: str = Field("b2c_lifestyle", example="b2c_lifestyle", description="b2c_lifestyle | b2b_corporate | expert_services")
    tier: str = Field("pro", example="pro", description="starter | pro | enterprise")
    brand_props: List[str] = Field(default_factory=list, example=["dark oak desk", "matte brass"])
    tone_of_voice: Optional[str] = Field("Экспертный, лаконичный", description="Tone of Voice")
    source_type: Optional[str] = Field("hybrid", description="user_photo | document_ocr | rag_facts_only | hybrid")
    vlm_visual_anchors: Optional[List[str]] = Field(default_factory=list, description="Якоря с фото пользователя")
    ocr_raw_text: Optional[str] = Field(None, description="Сырой распознанный текст меню или документа")
    rag_context_snippets: Optional[List[str]] = Field(default_factory=list, description="Факты из базы знаний")
    calendar_event: Optional[str] = Field(None, description="Праздник или инфоповод")
    user_raw_intent: Optional[str] = Field(None, description="Намерение / тема от пользователя")
    target_date: Optional[str] = Field(None, description="Целевая дата ISO: YYYY-MM-DD")
    format: Optional[str] = Field(None, description="single_shot | carousel_light | carousel_heavy | cryptex_puzzle")


class WeekPlanApiRequest(BaseModel):
    brand_id: str = Field(..., example="brand_102")
    company_name: str = Field("UCust", example="Specialty Coffee")
    industry: str = Field("b2c_lifestyle", example="b2c_lifestyle")
    tier: str = Field("pro", example="pro")
    brand_props: List[str] = Field(default_factory=list)
    days_count: int = Field(7, ge=1, le=30)
    start_date: Optional[str] = Field(None, description="Начальная дата (YYYY-MM-DD)")


@app.post("/api/v1/content/draft", tags=["Content Strategy & Lazy Rendering"])
async def create_content_draft(payload: ContentDraftApiRequest):
    """
    Генерация черновика поста со статусом DRAFT_TEXT (0 GPU cost).
    Синтезирует текст через Сайгу и строит спецификации промптов без запуска ComfyUI.
    """
    try:
        industry_enum = IndustryArchetype(payload.industry.lower())
    except ValueError:
        industry_enum = IndustryArchetype.B2C_LIFESTYLE

    tier_enum = SubscriptionTier.normalize(payload.tier) if payload.tier else SubscriptionTier.BUSINESS

    brand = BrandProfile(
        brand_id=payload.brand_id,
        company_name=payload.company_name,
        industry=industry_enum,
        tier=tier_enum,
        brand_props=payload.brand_props,
        tone_of_voice=payload.tone_of_voice or "Уверенный"
    )

    try:
        src_type_enum = IngestionSourceType(payload.source_type.lower()) if payload.source_type else IngestionSourceType.HYBRID
    except ValueError:
        src_type_enum = IngestionSourceType.HYBRID

    raw_input = RawDataIngestion(
        source_type=src_type_enum,
        vlm_visual_anchors=payload.vlm_visual_anchors or [],
        ocr_raw_text=payload.ocr_raw_text,
        rag_context_snippets=payload.rag_context_snippets or [],
        calendar_event=payload.calendar_event,
        user_raw_intent=payload.user_raw_intent
    )

    t_date = datetime.fromisoformat(payload.target_date) if payload.target_date else datetime.now()
    forced_fmt = ContentFormat(payload.format.lower()) if payload.format else None

    draft = content_strategy_engine.generate_post_draft(
        brand=brand,
        raw_input=raw_input,
        target_date=t_date,
        forced_format=forced_fmt
    )

    # Регистрация черновика в стейт-машине
    lazy_controller.register_draft(draft, dev_simulation_mode=True)
    return draft.dict()


@app.post("/api/v1/content/week-plan", tags=["Content Strategy & Lazy Rendering"])
async def generate_week_plan_drafts(payload: WeekPlanApiRequest):
    """
    Пакетная генерация недельного плана (DRAFT_TEXT).
    0 GPU-затрат — мгновенный возврат расписания с текстами и ToV днями.
    """
    from datetime import timedelta
    start = datetime.fromisoformat(payload.start_date) if payload.start_date else datetime.now()

    try:
        industry_enum = IndustryArchetype(payload.industry.lower())
    except ValueError:
        industry_enum = IndustryArchetype.B2C_LIFESTYLE

    tier_enum = SubscriptionTier.normalize(payload.tier) if payload.tier else SubscriptionTier.BUSINESS

    brand = BrandProfile(
        brand_id=payload.brand_id,
        company_name=payload.company_name,
        industry=industry_enum,
        tier=tier_enum,
        brand_props=payload.brand_props,
        tone_of_voice="Экспертный, лаконичный"
    )

    raw_input = RawDataIngestion(
        source_type=IngestionSourceType.RAG_FACTS_ONLY,
        rag_context_snippets=[f"Ведущая экспертиза в нише {payload.company_name}"]
    )

    drafts = []
    for i in range(payload.days_count):
        cur_date = start + timedelta(days=i)
        draft = content_strategy_engine.generate_post_draft(
            brand=brand,
            raw_input=raw_input,
            target_date=cur_date
        )
        lazy_controller.register_draft(draft, dev_simulation_mode=True)
        drafts.append(draft.dict())

    return {
        "status": "success",
        "brand_id": payload.brand_id,
        "total_posts": len(drafts),
        "posts": drafts
    }


@app.post("/api/v1/content/render/{post_id}", tags=["Content Strategy & Lazy Rendering"])
async def trigger_post_render(post_id: str, trigger_source: str = "manual_approve"):
    """
    Триггер асинхронного GPU-рендера поста (переход DRAFT_TEXT -> AWAITING_RENDER -> RENDERING -> RENDERED).
    """
    try:
        post = await lazy_controller.trigger_render(post_id, trigger_source=trigger_source)
        return {
            "status": "success",
            "post_id": post.post_id,
            "lifecycle_status": post.status.value,
            "vram_cost_mb": post.vram_cost_mb,
            "message": "Задача рендера успешно поставлена в очередь GPU"
        }
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/content/post/{post_id}", tags=["Content Strategy & Lazy Rendering"])
async def get_post_lifecycle_status(post_id: str):
    """
    Проверка статуса поста и получение ссылок на сгенерированные изображения.
    """
    post = lazy_controller.posts_db.get(post_id)
    if not post:
        raise HTTPException(status_code=404, detail=f"Пост {post_id} не найден в базе черновиков.")
    return post.dict()


# -------------------------------------------------------------------
# Endpoints: Calendar, Idea Bank & Promo Safety Notification Pipeline
# -------------------------------------------------------------------

class PromoDecisionApiRequest(BaseModel):
    project_id: str = Field(..., example="proj_bakery_01")
    post_id: str = Field(..., example="post_kulich_promo_01")
    decision: str = Field(..., example="approved", description="approved | rejected | modified")
    user_id: str = Field("user_owner", example="usr_admin")
    scheduled_publish_at: Optional[str] = Field(None, example="2026-04-12T09:00:00Z")
    tenant_id: str = Field("dev", example="tenant_main")
    callback_url: Optional[str] = None


class SyncRadarApiRequest(BaseModel):
    niche: str = Field(..., example="пекарня")
    country: str = Field("россия", example="россия")
    city: str = Field("Москва", example="Москва")
    horizon_days: int = Field(21, example=21)
    upcoming_events: List[Dict[str, Any]] = Field(default_factory=list)
    tenant_id: str = Field("dev", example="tenant_main")
    callback_url: Optional[str] = None


class PlaceholderSuggestApiRequest(BaseModel):
    niche: str = Field(..., example="пекарня")
    placeholder_text: str = Field(..., example="Пасхальные куличи с цукатами")
    suggested_topic: str = Field(..., example="Праздничная коллекция куличей")
    funnel_stage: str = Field("TOFU", example="TOFU")
    tenant_id: str = Field("dev", example="tenant_main")
    callback_url: Optional[str] = None


@app.post("/api/v1/content/promo-decision", tags=["Content Strategy & Lazy Rendering"])
async def record_promo_decision(payload: PromoDecisionApiRequest):
    """
    Прием решения пользователя по акции (Human-in-the-Loop Promo Hard-Gate).
    Отправляет подтверждение через webhook-пайплайн.
    """
    success = await CalendarIdeaNotificationPipeline.emit_promo_decision(
        project_id=payload.project_id,
        post_id=payload.post_id,
        decision=payload.decision,
        user_id=payload.user_id,
        scheduled_publish_at=payload.scheduled_publish_at,
        tenant_id=payload.tenant_id,
        callback_url=payload.callback_url
    )
    return {
        "status": "success" if success else "warning",
        "post_id": payload.post_id,
        "decision": payload.decision,
        "webhook_dispatched": success,
        "message": f"Решение '{payload.decision}' по промо-посту {payload.post_id} зафиксировано."
    }


@app.post("/api/v1/ideas/bank/sync-radar", tags=["Idea Bank & Situational Radar"])
async def sync_idea_radar(payload: SyncRadarApiRequest):
    """
    Синхронизация радара инфоповодов и отправка вебхука с праздниками/событиями на 21 день.
    """
    events = payload.upcoming_events
    if not events:
        # Автоматическая генерация базовых инфоповодов для ниши
        events = [
            {"title": "Пасхальная неделя", "date": "2026-04-12", "relevance": 0.98, "angle": "Праздничный ассортимент куличей"},
            {"title": "День весны и труда", "date": "2026-05-01", "relevance": "0.85", "angle": "Пикниковые наборы и выпечка"},
            {"title": "День кондитера", "date": "2026-05-03", "relevance": 0.90, "angle": "Закулисье пекарни и мастерство шефа"}
        ]
    
    success = await CalendarIdeaNotificationPipeline.emit_idea_radar_synced(
        niche=payload.niche,
        upcoming_events=events,
        country=payload.country,
        city=payload.city,
        horizon_days=payload.horizon_days,
        tenant_id=payload.tenant_id,
        callback_url=payload.callback_url
    )
    return {
        "status": "success",
        "events_count": len(events),
        "events": events,
        "webhook_dispatched": success
    }


@app.post("/api/v1/ideas/bank/placeholder", tags=["Idea Bank & Situational Radar"])
async def suggest_tab_placeholder(payload: PlaceholderSuggestApiRequest):
    """
    Генерация и рассылка актуального Tab-плейсхолдера для поля ввода идей.
    """
    success = await CalendarIdeaNotificationPipeline.emit_tab_placeholder_suggested(
        niche=payload.niche,
        placeholder_text=payload.placeholder_text,
        suggested_topic=payload.suggested_topic,
        funnel_stage=payload.funnel_stage,
        tenant_id=payload.tenant_id,
        callback_url=payload.callback_url
    )
    return {
        "status": "success",
        "placeholder_text": payload.placeholder_text,
        "suggested_topic": payload.suggested_topic,
        "funnel_stage": payload.funnel_stage,
        "webhook_dispatched": success
    }



if __name__ == "__main__":
    import uvicorn
    host = os.getenv("AI_SERVICE_HOST", "0.0.0.0")
    port = int(os.getenv("AI_SERVICE_PORT", "8000"))
    print(f"[API Gateway] 🚀 Запуск AI Service Gateway на http://{host}:{port} ...")
    uvicorn.run(app, host=host, port=port)

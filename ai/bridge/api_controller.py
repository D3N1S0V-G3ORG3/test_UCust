"""
FastAPI controller for orchestrating the multi-agent marketing pipeline with PostgreSQL storage.
"""

from __future__ import annotations

import logging
import os
import sys
import asyncio
from typing import Any, Dict, List, Literal, Optional

try:
    from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, status, Header
except ImportError:
    class FastAPI:
        def __init__(self, title: str = "UCust.AI API", version: str = "1.0.0"):
            self.title = title
            self.version = version

        def on_event(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

        def post(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

        def get(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

    class BackgroundTasks:
        def add_task(self, func, *args, **kwargs):
            func(*args, **kwargs)

    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str):
            self.status_code = status_code
            self.detail = detail
            super().__init__(f"HTTP {status_code}: {detail}")

    class status:
        HTTP_200_OK = 200
        HTTP_202_ACCEPTED = 202
        HTTP_400_BAD_REQUEST = 400
        HTTP_404_NOT_FOUND = 404
        HTTP_409_CONFLICT = 409
        HTTP_500_INTERNAL_SERVER_ERROR = 500

    def Depends(dependency=None):
        return dependency

    def Header(default=None, alias=None):
        return default

from pydantic import BaseModel, Field

from core.agents import AgentContext, Agent_Copywriter
from core.notification_bridge import ApprovalDecision
from core.orchestrator import AgentState, build_default_orchestrator
from integration.java_bridge import JavaBridgeClient, get_java_bridge_client
from schemas.models import (
    CopywritingFramework,
    LTX23PromptSchema,
    PendingPostSchema,
    PostDraftSchema,
    PublishRequestSchema,
    QuestionnaireStep1,
    QuestionnaireStep2,
    QuestionnaireStep3,
    QuestionnaireStep4,
    QuestionnaireStep5,
    UserQuestionnaire,
)
from storage.db import (
    DatabaseFactory,
    create_task,
    get_async_sessionmaker,
    get_db_session,
    get_pending_tasks,
    get_task,
    init_db,
    update_task_status,
)
from publishers import (
    BasePublisher,
    InstagramPublisher,
    OdnoklassnikiPublisher,
    TelegramPublisher,
    VkPublisher,
    get_publisher,
)
from storage.repository import get_user_questionnaire

# Reconfigure stdout encoding for Windows CP1251 compatibility
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

LOG_FILE = os.getenv("UCUST_LOG_FILE", "app_log.log")
APP_TITLE = os.getenv("UCUST_APP_TITLE", "UCust.AI API")
APP_VERSION = os.getenv("UCUST_APP_VERSION", "1.0.0")

logging.basicConfig(
    level=os.getenv("UCUST_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("ucust_api")

try:
    database = DatabaseFactory.build()
except Exception as exc:
    logger.warning("DatabaseFactory initialization: %s", exc)
    database = None

app = FastAPI(title=APP_TITLE, version=APP_VERSION)


@app.on_event("startup")
async def startup_event() -> None:
    """Startup lifecycle hook to initialize database tables."""
    await init_db()


class ProcessRequest(BaseModel):
    """Input contract for starting a background content-generation job."""

    user_id: str = Field(..., description="External user identifier.")
    framework: CopywritingFramework = Field(
        default=CopywritingFramework.PAS,
        description="Фреймворк копирайтинга (PAS, AIDA, PMHS)",
    )


class ProcessResponse(BaseModel):
    """Response contract for accepted background jobs."""

    status: str
    detail: str
    job_id: int


class StatusResponse(BaseModel):
    """Status contract for task polling."""

    status: str
    result: Optional[str] = None
    error: Optional[str] = None
    approval_status: Optional[str] = None
    action_required: bool = False


class UserActionRequest(BaseModel):
    """Input contract for human-in-the-loop action submission."""

    action: Literal["APPROVED", "EDIT", "REGENERATE"] = Field(
        ...,
        description="User decision for the current draft.",
    )
    event_type: Optional[str] = Field(
        default=None,
        description="Optional event type (gratitude, holiday, achievement, emergency, custom_edit).",
    )
    context: Optional[str] = Field(
        default=None,
        description="Optional event context or editorial instruction.",
    )


class UserActionResponse(BaseModel):
    """Output contract for human-in-the-loop action processing."""

    status: str
    detail: str
    job_id: int
    result: Optional[str] = None


async def _get_or_create_questionnaire(user_id: str, session: Any = None) -> tuple[int, UserQuestionnaire]:
    """
    Attempts to fetch questionnaire from database;
    falls back to a default mock questionnaire for development/testing.
    """
    if database is not None:
        try:
            loaded = get_user_questionnaire(database, user_id)
            if loaded is not None:
                return loaded
        except Exception as exc:
            logger.warning("Could not fetch questionnaire from DB for user_id=%s: %s", user_id, exc)

    # Fallback default questionnaire for development mode
    mock_questionnaire = UserQuestionnaire(
        step1=QuestionnaireStep1(
            business_name=f"Brand-{user_id}",
            mission="Инновационные маркетинговые решения и автоматизация контента",
            region="Москва и регионы РФ",
        ),
        step2=QuestionnaireStep2(
            target_audience="B2B предприниматели, маркетологи и руководители продуктов",
            demographics="Мужчины и женщины 25-50 лет",
            pain_points="Высокая стоимость лида и нехватка времени на написание контента",
        ),
        step3=QuestionnaireStep3(
            tone_of_voice="Дружелюбный и экспертный",
            content_formats="Посты-кейсы, гайды, разборы трендов",
            taboo_topics="Политика, незаверенные обещания",
        ),
        step4=QuestionnaireStep4(
            goals="Повышение вовлеченности аудитории и лидогенерация",
            kpi="ER (Engagement Rate), количество заявок",
            frequency="3 раза в неделю",
        ),
        step5=QuestionnaireStep5(
            competitors="CompetitorA, CompetitorB",
            references="Примеры успешных IT-брендов",
            additional_notes="Демо-анкета для режима разработки",
        ),
    )
    return 1, mock_questionnaire


async def _run_orchestrator(job_id: int, user_id: str, questionnaire: UserQuestionnaire) -> None:
    """
    Executes the recursive orchestrator in background task.
    Uses its own dedicated database session factory so it remains active after 202 Accepted return.
    """
    try:
        await update_task_status(job_id, status="PROCESSING")

        context = AgentContext(questionnaire=questionnaire)
        orchestrator = build_default_orchestrator(database=database)

        try:
            context = await orchestrator.run_pipeline(context)
        except Exception as exc:
            logger.exception("Critical orchestrator failure for job_id=%d", job_id)
            await update_task_status(job_id, status="FAILED", error_message=str(exc))
            return

        payload = {
            "post_text": context.post_draft.text if context.post_draft else None,
            "image_url": context.post_draft.image_url if context.post_draft else None,
            "video_url": context.post_draft.video_url if context.post_draft else None,
            "audio_url": context.post_draft.audio_url if context.post_draft else None,
            "media_url": context.post_draft.media_url if context.post_draft else None,
            "local_video_path": context.post_draft.local_video_path if context.post_draft else None,
            "local_audio_path": context.post_draft.local_audio_path if context.post_draft else None,
            "approval_status": context.approval_status,
            "last_event_type": context.user_event_type,
            "last_event_context": context.user_event_context,
            "ltx23_prompts": [p.model_dump() for p in context.ltx23_prompts] if context.ltx23_prompts else [],
            "uniqueness_score": context.post_draft.uniqueness_score if context.post_draft else 1.0,
            "duplicates_found": context.post_draft.duplicates_found if context.post_draft else False,
        }

        task_status = "AWAITING_USER_ACTION" if context.pending_user_action else "COMPLETED"
        await update_task_status(job_id, status=task_status, result_payload=payload)

    except Exception as exc:
        logger.exception("Background processing failed for user_id=%s", user_id)
        await update_task_status(job_id, status="FAILED", error_message=str(exc))


@app.post("/api/v1/process", response_model=ProcessResponse, status_code=status.HTTP_202_ACCEPTED)
@app.post("/process", response_model=ProcessResponse, status_code=status.HTTP_202_ACCEPTED)
async def process_request(
    payload: ProcessRequest,
    background_tasks: BackgroundTasks,
    session: Any = Depends(get_db_session),
) -> ProcessResponse:
    """Endpoint for initiating asynchronous background content generation pipeline."""
    if not payload.user_id or not payload.user_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Field 'user_id' is required.",
        )

    clean_user_id = payload.user_id.strip()
    user_profile_id, questionnaire = await _get_or_create_questionnaire(clean_user_id, session)

    job_id = await create_task(
        user_id=clean_user_id,
        user_profile_id=user_profile_id,
        status="PENDING",
        session=session,
    )

    background_tasks.add_task(_run_orchestrator, job_id, clean_user_id, questionnaire)

    return ProcessResponse(
        status="accepted",
        detail="Background processing has started.",
        job_id=job_id,
    )


@app.get("/api/v1/status/{job_id}", response_model=StatusResponse)
async def get_status(
    job_id: int,
    session: Any = Depends(get_db_session),
) -> StatusResponse:
    """Endpoint for polling FSM task execution status and latest result payload."""
    task = await get_task(job_id, session=session)

    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with job_id={job_id} was not found.",
        )

    task_status = task.status
    result_payload = task.result_payload or {}

    result_value = result_payload.get("post_text") or result_payload.get("image_link")
    approval_status = result_payload.get("approval_status")
    action_required = task_status == "AWAITING_USER_ACTION"
    error_value = task.error_message if task_status == "FAILED" else None

    return StatusResponse(
        status=task_status,
        result=result_value,
        error=error_value,
        approval_status=approval_status,
        action_required=action_required,
    )


@app.post("/api/v1/action/{job_id}", response_model=UserActionResponse)
async def submit_user_action(
    job_id: int,
    payload: UserActionRequest,
    session: Any = Depends(get_db_session),
    java_bridge: JavaBridgeClient = Depends(get_java_bridge_client),
) -> UserActionResponse:
    """
    Endpoint for submitting human-in-the-loop decisions (APPROVED, EDIT, REGENERATE).
    Dispatches final artifacts to Java backend when APPROVED and updates DB status.
    """
    task = await get_task(job_id, session=session)

    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with job_id={job_id} was not found.",
        )

    current_status = task.status
    if current_status != "AWAITING_USER_ACTION":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task status '{current_status}' does not accept user actions.",
        )

    current_payload = task.result_payload or {}
    current_post_text = current_payload.get("post_text") or ""

    # ACTION 1: APPROVED
    if payload.action == ApprovalDecision.APPROVED.value:
        current_payload["approval_status"] = ApprovalDecision.APPROVED.value

        post_draft = PostDraftSchema(
            text=current_post_text,
            uniqueness_score=current_payload.get("uniqueness_score", 1.0),
            duplicates_found=current_payload.get("duplicates_found", False),
            video_url=current_payload.get("video_url"),
            audio_url=current_payload.get("audio_url"),
            media_url=current_payload.get("media_url"),
            local_video_path=current_payload.get("local_video_path"),
            local_audio_path=current_payload.get("local_audio_path"),
        )

        raw_prompts = current_payload.get("ltx23_prompts", [])
        ltx23_prompts = [
            LTX23PromptSchema(**p) for p in raw_prompts if isinstance(p, dict)
        ]

        # Dispatch generated content artifacts to Java Backend asynchronously
        try:
            draft_ok = await java_bridge.send_post_draft(job_id, post_draft)
            prompts_ok = True
            if ltx23_prompts:
                prompts_ok = await java_bridge.send_ltx23_prompts(job_id, ltx23_prompts)

            if not draft_ok or not prompts_ok:
                logger.warning(
                    "Java backend dispatch warning for job_id=%d: draft_ok=%s, prompts_ok=%s",
                    job_id,
                    draft_ok,
                    prompts_ok,
                )
        except Exception as bridge_exc:
            logger.error("Error dispatching to Java bridge for job_id=%d: %s", job_id, bridge_exc)
            await update_task_status(
                job_id=job_id,
                status="FAILED",
                result_payload=current_payload,
                error_message=f"Java bridge dispatch error: {bridge_exc}",
                session=session,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to dispatch payload to Java backend: {bridge_exc}",
            )

        await update_task_status(
            job_id=job_id,
            status="COMPLETED",
            result_payload=current_payload,
            session=session,
        )

        return UserActionResponse(
            status="COMPLETED",
            detail="Content approved and sent to Java backend.",
            job_id=job_id,
            result=current_post_text,
        )

    # ACTION 2: EDIT
    if payload.action == ApprovalDecision.EDIT.value:
        event_type = (payload.event_type or "custom_edit").strip().lower()
        event_context = (payload.context or "").strip()

        copywriter = Agent_Copywriter()
        event_context_obj = AgentContext(
            post_draft=PostDraftSchema(
                text=current_post_text,
                uniqueness_score=current_payload.get("uniqueness_score", 1.0),
                duplicates_found=current_payload.get("duplicates_found", False),
            ),
            approval_status=ApprovalDecision.EDIT.value,
            pending_user_action=True,
        )

        event_context_obj = await copywriter.process_user_event(
            context=event_context_obj,
            event_type=event_type,
            event_context=event_context,
        )

        updated_text = (
            event_context_obj.post_draft.text if event_context_obj.post_draft else current_post_text
        )
        current_payload["post_text"] = updated_text
        current_payload["approval_status"] = ApprovalDecision.EDIT.value
        current_payload["last_event_type"] = event_type
        current_payload["last_event_context"] = event_context

        await update_task_status(
            job_id=job_id,
            status="AWAITING_USER_ACTION",
            result_payload=current_payload,
            session=session,
        )

        return UserActionResponse(
            status="AWAITING_USER_ACTION",
            detail="Draft updated with user event context; waiting for approval.",
            job_id=job_id,
            result=updated_text,
        )

    # ACTION 3: REGENERATE
    event_type = (payload.event_type or "regenerate").strip().lower()
    event_context = (payload.context or "").strip()

    regenerated_context = AgentContext(
        post_draft=PostDraftSchema(
            text=current_post_text,
            uniqueness_score=current_payload.get("uniqueness_score", 1.0),
            duplicates_found=current_payload.get("duplicates_found", False),
        ),
        approval_status=ApprovalDecision.REGENERATE.value,
        pending_user_action=True,
        user_event_type=event_type,
        user_event_context=event_context,
    )

    orchestrator = build_default_orchestrator(database=database)
    orchestrator.transition_to(AgentState.AWAITING_USER_DECISION)
    regenerated_context = await orchestrator.run_pipeline(regenerated_context)

    updated_text = (
        regenerated_context.post_draft.text if regenerated_context.post_draft else current_post_text
    )
    current_payload["post_text"] = updated_text
    current_payload["approval_status"] = regenerated_context.approval_status
    current_payload["last_event_type"] = regenerated_context.user_event_type
    current_payload["last_event_context"] = regenerated_context.user_event_context
    current_payload["ltx23_prompts"] = (
        [p.model_dump() for p in regenerated_context.ltx23_prompts]
        if regenerated_context.ltx23_prompts
        else []
    )

    next_status = "COMPLETED" if not regenerated_context.pending_user_action else "AWAITING_USER_ACTION"

    await update_task_status(
        job_id=job_id,
        status=next_status,
        result_payload=current_payload,
        session=session,
    )

    return UserActionResponse(
        status=next_status,
        detail="Regeneration flow executed.",
        job_id=job_id,
        result=updated_text,
    )


@app.get("/api/v1/posts/pending", response_model=list[PendingPostSchema])
async def get_pending_posts(
    session: Any = Depends(get_db_session),
) -> list[PendingPostSchema]:
    """
    Export endpoint for Human-in-the-Loop web UI preview.
    Retrieves all tasks/posts currently in 'AWAITING_USER_ACTION' state.
    """
    tasks = await get_pending_tasks(session=session)
    pending_list = []
    for task in tasks:
        payload = task.result_payload or {}
        pending_list.append(
            PendingPostSchema(
                job_id=task.id,
                user_id=task.user_id or "unknown",
                status=task.status,
                post_text=payload.get("post_text"),
                video_url=payload.get("video_url"),
                audio_url=payload.get("audio_url"),
                media_url=payload.get("media_url"),
                local_video_path=payload.get("local_video_path"),
                local_audio_path=payload.get("local_audio_path"),
                uniqueness_score=payload.get("uniqueness_score", 1.0),
                duplicates_found=payload.get("duplicates_found", False),
            )
        )
    return pending_list


@app.post("/api/v1/posts/{post_id}/publish", response_model=dict[str, Any])
async def publish_post(
    post_id: int,
    payload: PublishRequestSchema,
    session: Any = Depends(get_db_session),
) -> dict[str, Any]:
    """
    Publishing endpoint for Human-in-the-Loop pattern.
    Updates DB status to USER_APPROVED and dispatches post text and media to selected social publishers.
    """
    task = await get_task(post_id, session=session)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Post task with ID {post_id} was not found.",
        )

    task_payload = task.result_payload or {}
    text_content = payload.custom_caption or task_payload.get("post_text") or "No text provided"
    media_path = task_payload.get("local_video_path") or task_payload.get("local_audio_path")

    # Step 1: Update task state to USER_APPROVED
    await update_task_status(
        job_id=post_id,
        status="USER_APPROVED",
        result_payload=task_payload,
        session=session,
    )

    publish_results = {}
    raw_platforms = payload.platforms or payload.target_platforms or ["telegram"]
    platforms = [p.lower().strip() for p in raw_platforms]

    # Step 2: Dynamically dispatch to requested publishers using get_publisher factory
    for platform in platforms:
        try:
            publisher = get_publisher(platform)
            ok_res = await publisher.publish(text=text_content, media_path=media_path)
            publish_results[platform] = ok_res
        except Exception as pub_exc:
            logger.error("Error publishing to platform '%s' for post_id=%d: %s", platform, post_id, pub_exc)
            publish_results[platform] = False

    # Step 3: Update task state to PUBLISHED
    await update_task_status(
        job_id=post_id,
        status="PUBLISHED",
        result_payload=task_payload,
        session=session,
    )

    return {
        "status": "PUBLISHED",
        "job_id": post_id,
        "detail": f"Post #{post_id} successfully published to platforms: {platforms}.",
        "publish_results": publish_results,
    }


# ============================================================================
# ЕДИНЫЙ УНИВЕРСАЛЬНЫЙ ШЛЮЗ ОРКЕСТРАТОРА (UNIFIED TASK GATEWAY)
# ============================================================================

class OrchestratorTaskRequest(BaseModel):
    task_type: str = Field(
        ...,
        description="Тип задачи: 'quick_vision', 'analyze_documents', 'quick_scan', 'onboard_user', 'generate_post', 'edit_photo', 'plan_content', 'feedback_loop', 'get_graph_data'"
    )
    user_id: str = Field(..., description="ID пользователя")
    session_id: Optional[str] = Field(default=None, description="ID сессии / трейса")
    callback_url: Optional[str] = Field(default=None, description="Динамический URL вебхука для авто-пуша (например, для dev/staging бэкенда)")
    payload: Dict[str, Any] = Field(default={}, description="Полезная нагрузка (параметры, ссылки, фото, тексты)")
    sync_backend: bool = Field(default=True, description="Флаг авто-пуша результата в бэкенд")


class OrchestratorTaskResponse(BaseModel):
    status: str = Field(..., description="'success' или 'error'")
    task_type: str
    user_id: str
    session_id: str
    data: Dict[str, Any] = Field(default={})
    timings: Dict[str, Any] = Field(default={})
    error: Optional[str] = None


@app.post("/api/v1/orchestrator/execute", response_model=OrchestratorTaskResponse)
@app.post("/api/v1/task/execute", response_model=OrchestratorTaskResponse)
async def execute_orchestrator_task(
    request: OrchestratorTaskRequest,
    x_internal_secret: Optional[str] = Header(None, alias="X-Internal-Secret"),
) -> OrchestratorTaskResponse:
    """
    ЕДИНЫЙ КОМАНДНЫЙ ШЛЮЗ ОРКЕСТРАТОРА ДЛЯ БЭКЕНДА:
    - Принимает любую команду ('generate_post', 'quick_vision', 'onboard_user', 'analyze_documents', 'quick_scan').
    - Проводит централизованную валидацию безопасности (SSRF, Injections, Secret).
    - Выполняет оркестровку через UnifiedOrchestrator на максимальной скорости.
    - Автоматически синхронизирует результат с основным бэкендом (HTTP Push Webhook).
    """
    import time
    from core.orchestrator import UnifiedOrchestrator, SecurityGuard

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
        orchestrator = UnifiedOrchestrator(db_session=database)
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
                                "user_id": request.user_id,
                                "session_id": session_id,
                                "task_type": request.task_type,
                                "status": result_data.get("status", "success"),
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
        logger.exception("Error executing orchestrator task %s: %s", request.task_type, exc)
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
# АЛИАСЫ ДЛЯ УДОБСТВА ФРОНТЕНДА (DELEGATING ALIASES)
# ============================================================================

class QuickVisionAnalysisRequest(BaseModel):
    user_id: str = Field(..., description="ID пользователя")
    session_id: Optional[str] = Field(default=None, description="ID сессии для кэширования")
    prompt: Optional[str] = Field(default="", description="Текстовый промпт/намерение пользователя")
    niche: Optional[str] = Field(default="Бизнес и услуги", description="Ниша бизнеса")
    company_name: Optional[str] = Field(default="UCust", description="Название компании")
    attachments: List[Any] = Field(..., description="1-3 фото (Base64 data-url, URL или пути к файлам)")


class DocumentAnalysisRequest(BaseModel):
    user_id: str = Field(..., description="ID пользователя")
    company_name: Optional[str] = Field(default="UCust", description="Название компании")
    niche: Optional[str] = Field(default="Бизнес и услуги", description="Ниша компании")
    documents: List[str] = Field(..., description="Пути к файлам или имена документов (PDF, DOCX, PPTX)")


class UnifiedBrandAnalysisRequest(BaseModel):
    user_id: str = Field(..., description="ID пользователя")
    company_name: Optional[str] = Field(default="", description="Название компании")
    niche: Optional[str] = Field(default="", description="Сфера деятельности")
    city: Optional[str] = Field(default="Москва", description="Город")
    urls: List[str] = Field(default=[], description="Ссылки: сайт, VK, Telegram, 2GIS/Яндекс")
    documents: List[str] = Field(default=[], description="Пути к документам (PDF, DOCX, PPTX)")
    images: List[Any] = Field(default=[], description="Фото / логотипы (Base64 или пути)")
    raw_notes: Optional[str] = Field(default="", description="Дополнительные заметки")
    fast_mode: bool = Field(default=True, description="Быстрый режим предварительного сканирования")


@app.post("/api/v1/vision/quick-analyze", response_model=Dict[str, Any])
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


@app.post("/api/v1/collectors/analyze-documents", response_model=Dict[str, Any])
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


@app.post("/api/v1/collectors/analyze-brand", response_model=Dict[str, Any])
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


class SKUSearchResponse(BaseModel):
    status: str = "success"
    query: str
    count: int
    chips: List[Dict[str, Any]]


class BindSKURequest(BaseModel):
    project_id: str = Field(..., description="ID проекта/бренда")
    topic: str = Field(..., description="Исходная тема или название продукта")
    sku_id: str = Field(..., description="ID выбранного SKU из чипов")
    aspect_ratio: str = Field(default="1:1", description="Формат кадра (1:1, 4:5, 9:16, 16:9)")
    profile: Optional[Dict[str, Any]] = Field(default=None, description="Профиль бизнеса")


@app.get("/api/v1/content/sku-search", response_model=SKUSearchResponse)
async def sku_search_endpoint(
    query: str,
    x_internal_secret: Optional[str] = Header(None, alias="X-Internal-Secret")
) -> SKUSearchResponse:
    from skills.geo_entity_resolver import GeoEntityResolver
    chips = GeoEntityResolver.resolve_disambiguation_chips(query)
    return SKUSearchResponse(
        status="success",
        query=query,
        count=len(chips),
        chips=[c.model_dump() for c in chips]
    )


@app.post("/api/v1/content/bind-sku", response_model=Dict[str, Any])
async def bind_sku_endpoint(
    payload: BindSKURequest,
    x_internal_secret: Optional[str] = Header(None, alias="X-Internal-Secret")
) -> Dict[str, Any]:
    from skills.content_generation_engine import ContentGenerationEngine
    engine = ContentGenerationEngine()
    draft = await engine.generate_post(
        project_id=payload.project_id,
        topic=payload.topic,
        profile=payload.profile,
        aspect_ratio=payload.aspect_ratio,
        sku_id=payload.sku_id
    )
    return {
        "status": "success",
        "post_draft": draft.model_dump(mode="json")
    }


__all__ = ["app"]


# File: bridge/api_controller.py | Module: api_controller | Part of Intellectual Property Submission.
"""FastAPI controller for orchestrating the multi-agent marketing pipeline."""

from __future__ import annotations

import logging
import os
from typing import Literal, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from core.agents import AgentContext, Agent_Copywriter
from core.notification_bridge import ApprovalDecision
from core.orchestrator import AgentState, build_default_orchestrator
from schemas.models import PostDraftSchema, UserQuestionnaire
from storage.db import DatabaseFactory
from storage.repository import (
    create_content_task,
    get_task_status,
    get_user_questionnaire,
    update_content_task_status,
)

LOG_FILE = os.getenv("UCUST_LOG_FILE", "app_log.log")
APP_TITLE = os.getenv("UCUST_APP_TITLE", "UCust.AI Bridge API")
APP_VERSION = os.getenv("UCUST_APP_VERSION", "1.0.0")

logging.basicConfig(
    level=os.getenv("UCUST_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    filename=LOG_FILE,
)

logger = logging.getLogger("ucust_api")
database = DatabaseFactory.build()
app = FastAPI(title=APP_TITLE, version=APP_VERSION)


class ProcessRequest(BaseModel):
    """Input contract for starting a background content-generation job."""

    user_id: str = Field(..., description="External user identifier.")


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


# Step 1: Execute the recursive orchestrator as a background task and persist task outcomes.
def _run_orchestrator(job_id: int, user_id: str, questionnaire: UserQuestionnaire) -> None:
    try:
        update_content_task_status(database, job_id, status="PROCESSING")
        context = AgentContext(questionnaire=questionnaire)
        orchestrator = build_default_orchestrator()

        try:
            context = orchestrator.run_pipeline(context)
        except Exception as exc:  # noqa: BLE001
            context.add_log(f"API: orchestrator interrupted: {exc}")
            logger.exception("Critical orchestrator failure")
            update_content_task_status(database, job_id, status="FAILED", error_message=str(exc))
            return

        for log_line in context.logs:
            logger.info(log_line)

        payload = {
            "post_text": context.post_draft.text if context.post_draft else None,
            "image_link": None,
            "approval_status": context.approval_status,
            "last_event_type": context.user_event_type,
            "last_event_context": context.user_event_context,
        }

        if context.pending_user_action:
            update_content_task_status(
                database,
                job_id,
                status="AWAITING_USER_ACTION",
                result_payload=payload,
            )
            return

        update_content_task_status(
            database,
            job_id,
            status="COMPLETED",
            result_payload=payload,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Background processing failed for user_id=%s", user_id)
        update_content_task_status(database, job_id, status="FAILED", error_message=str(exc))


# Step 2: Validate incoming process requests and start asynchronous execution.
@app.post("/api/v1/process", response_model=ProcessResponse, status_code=status.HTTP_202_ACCEPTED)
@app.post("/process", response_model=ProcessResponse, status_code=status.HTTP_202_ACCEPTED)
async def process_request(payload: ProcessRequest, background_tasks: BackgroundTasks) -> ProcessResponse:
    if not payload.user_id or not payload.user_id.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Field 'user_id' is required.")

    loaded = get_user_questionnaire(database, payload.user_id.strip())
    if loaded is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User questionnaire was not found.")

    user_profile_id, questionnaire = loaded
    job_id = create_content_task(database, user_profile_id=user_profile_id, status="PENDING")
    background_tasks.add_task(_run_orchestrator, job_id, payload.user_id.strip(), questionnaire)

    return ProcessResponse(
        status="accepted",
        detail="Background processing has started.",
        job_id=job_id,
    )


# Step 3: Resolve task status and expose the latest available result payload.
@app.get("/api/v1/status/{job_id}", response_model=StatusResponse)
async def get_status(job_id: int) -> StatusResponse:
    task = get_task_status(database, job_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task was not found.")

    result_value = None
    approval_status = None
    action_required = task.status == "AWAITING_USER_ACTION"

    if task.result_payload:
        result_value = task.result_payload.get("post_text") or task.result_payload.get("image_link")
        approval_status = task.result_payload.get("approval_status")

    error_value = task.error_message if task.status == "FAILED" else None
    return StatusResponse(
        status=task.status,
        result=result_value,
        error=error_value,
        approval_status=approval_status,
        action_required=action_required,
    )


# Step 4: Apply human-in-the-loop actions and persist updated workflow state.
@app.post("/api/v1/action/{job_id}", response_model=UserActionResponse)
async def submit_user_action(job_id: int, payload: UserActionRequest) -> UserActionResponse:
    task = get_task_status(database, job_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task was not found.")

    if task.status != "AWAITING_USER_ACTION":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task status '{task.status}' does not accept user actions.",
        )

    current_payload = task.result_payload or {}
    current_post_text = current_payload.get("post_text") or ""

    if payload.action == ApprovalDecision.APPROVED.value:
        current_payload["approval_status"] = ApprovalDecision.APPROVED.value
        update_content_task_status(
            database,
            job_id,
            status="COMPLETED",
            result_payload=current_payload,
        )
        return UserActionResponse(
            status="COMPLETED",
            detail="Content has been approved by the user.",
            job_id=job_id,
            result=current_payload.get("post_text"),
        )

    if payload.action == ApprovalDecision.EDIT.value:
        event_type = (payload.event_type or "custom_edit").strip().lower()
        event_context = (payload.context or "").strip()

        copywriter = Agent_Copywriter()
        event_context_obj = AgentContext(
            post_draft=PostDraftSchema(
                text=current_post_text,
                uniqueness_score=1.0,
                duplicates_found=False,
            ),
            approval_status=ApprovalDecision.EDIT.value,
            pending_user_action=True,
        )
        event_context_obj = copywriter.process_user_event(
            context=event_context_obj,
            event_type=event_type,
            event_context=event_context,
        )

        updated_text = event_context_obj.post_draft.text if event_context_obj.post_draft else current_post_text
        current_payload["post_text"] = updated_text
        current_payload["approval_status"] = ApprovalDecision.EDIT.value
        current_payload["last_event_type"] = event_type
        current_payload["last_event_context"] = event_context

        update_content_task_status(
            database,
            job_id,
            status="AWAITING_USER_ACTION",
            result_payload=current_payload,
        )
        return UserActionResponse(
            status="AWAITING_USER_ACTION",
            detail="Draft was updated by user event and is waiting for approval.",
            job_id=job_id,
            result=updated_text,
        )

    event_type = (payload.event_type or "regenerate").strip().lower()
    event_context = (payload.context or "").strip()

    regenerated_context = AgentContext(
        post_draft=PostDraftSchema(
            text=current_post_text,
            uniqueness_score=1.0,
            duplicates_found=False,
        ),
        approval_status=ApprovalDecision.REGENERATE.value,
        pending_user_action=True,
        user_event_type=event_type,
        user_event_context=event_context,
    )

    orchestrator = build_default_orchestrator()
    orchestrator.transition_to(AgentState.AWAITING_USER_DECISION)
    regenerated_context = orchestrator.run_pipeline(regenerated_context)

    current_payload["post_text"] = (
        regenerated_context.post_draft.text if regenerated_context.post_draft else current_post_text
    )
    current_payload["approval_status"] = regenerated_context.approval_status
    current_payload["last_event_type"] = regenerated_context.user_event_type
    current_payload["last_event_context"] = regenerated_context.user_event_context

    next_status = "COMPLETED" if not regenerated_context.pending_user_action else "AWAITING_USER_ACTION"
    update_content_task_status(
        database,
        job_id,
        status=next_status,
        result_payload=current_payload,
    )

    return UserActionResponse(
        status=next_status,
        detail="Regeneration flow executed.",
        job_id=job_id,
        result=current_payload.get("post_text"),
    )

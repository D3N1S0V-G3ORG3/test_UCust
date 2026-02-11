"""
Репозиторий доступа к SQL-хранилищу.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple, Dict, Any

from sqlalchemy import or_

from schemas.models import (
    QuestionnaireStep1,
    QuestionnaireStep2,
    QuestionnaireStep3,
    QuestionnaireStep4,
    QuestionnaireStep5,
    UserQuestionnaire,
)
from storage.db import Database
from storage.models import ContentTask, UserProfile


def get_user_questionnaire(database: Database, user_id: str) -> Optional[Tuple[int, UserQuestionnaire]]:
    """
    Возвращает полную анкету пользователя по идентификатору.

    Использует SQL-хранилище для загрузки JSON-данных анкеты.
    """

    session = database.get_session()
    try:
        query = session.query(UserProfile)
        if user_id.isdigit():
            profile = (
                query.filter(
                    or_(
                        UserProfile.external_user_id == user_id,
                        UserProfile.id == int(user_id),
                    )
                )
                .order_by(UserProfile.id.desc())
                .first()
            )
        else:
            profile = query.filter(UserProfile.external_user_id == user_id).first()

        if profile is None:
            return None

        questionnaire = UserQuestionnaire(
            step1=QuestionnaireStep1(**profile.step1),
            step2=QuestionnaireStep2(**profile.step2),
            step3=QuestionnaireStep3(**profile.step3),
            step4=QuestionnaireStep4(**profile.step4),
            step5=QuestionnaireStep5(**profile.step5),
        )
        return profile.id, questionnaire
    finally:
        session.close()


def create_content_task(database: Database, user_profile_id: int, status: str = "PENDING") -> int:
    """
    Создает задачу контентного конвейера и возвращает ее идентификатор.
    """

    session = database.get_session()
    try:
        task = ContentTask(user_profile_id=user_profile_id, status=status)
        session.add(task)
        session.commit()
        session.refresh(task)
        return task.id
    finally:
        session.close()


def update_content_task_status(
    database: Database,
    task_id: int,
    status: str,
    error_message: Optional[str] = None,
    result_payload: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Обновляет статус задачи в SQL-хранилище.
    """

    session = database.get_session()
    try:
        task = session.query(ContentTask).filter(ContentTask.id == task_id).first()
        if task is None:
            return
        task.status = status
        task.error_message = error_message
        if result_payload is not None:
            task.result_payload = result_payload
        task.updated_at = datetime.utcnow()
        session.commit()
    finally:
        session.close()


def get_task_status(database: Database, task_id: int) -> Optional[ContentTask]:
    """
    Возвращает задачу контентного конвейера по идентификатору.
    """

    session = database.get_session()
    try:
        return session.query(ContentTask).filter(ContentTask.id == task_id).first()
    finally:
        session.close()

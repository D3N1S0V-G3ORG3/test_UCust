"""
Репозиторий доступа к SQL-хранилищу.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple, Dict, Any

from sqlalchemy import or_

try:
    from schemas.models import (
        QuestionnaireStep1,
        QuestionnaireStep2,
        QuestionnaireStep3,
        QuestionnaireStep4,
        QuestionnaireStep5,
        UserQuestionnaire,
        ActiveChannelsDTO,
    )
    from storage.db import Database
    from storage.models import ContentTask, UserProfile
except ImportError:
    from ai.schemas.models import (
        QuestionnaireStep1,
        QuestionnaireStep2,
        QuestionnaireStep3,
        QuestionnaireStep4,
        QuestionnaireStep5,
        UserQuestionnaire,
        ActiveChannelsDTO,
    )
    from ai.storage.db import Database
    from ai.storage.models import ContentTask, UserProfile


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


def get_active_connected_channels(
    database: Optional[Database] = None,
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    profile_data: Optional[Dict[str, Any]] = None
) -> List[str]:
    """
    Извлекает список только реально подключенных и активных каналов (is_active=True).
    Использует Anti-Corruption Layer (ActiveChannelsDTO) для строгой валидации и нормализации.
    Гарантирует детерминированный контракт List[str] с фоллбэком на ['telegram'].
    """
    raw_sources: List[Any] = []

    # 1. Сбор сырых данных из переданного словаря профиля
    if profile_data and isinstance(profile_data, dict):
        for key in ("target_channels", "connected_channels", "social_networks", "platforms", "social_links"):
            val = profile_data.get(key)
            if val is not None:
                raw_sources.append(val)

    # 2. Сбор сырых данных из базы данных, если в profile_data ничего не найдено
    if not raw_sources and database and user_id:
        session = database.get_session()
        try:
            query = session.query(UserProfile)
            if str(user_id).isdigit():
                profile = query.filter(or_(UserProfile.external_user_id == str(user_id), UserProfile.id == int(user_id))).first()
            else:
                profile = query.filter(UserProfile.external_user_id == str(user_id)).first()

            if profile:
                if profile.social_links:
                    raw_sources.append(profile.social_links)
                if hasattr(profile, "connected_channels") and getattr(profile, "connected_channels"):
                    raw_sources.append(getattr(profile, "connected_channels"))
                if hasattr(profile, "platforms") and getattr(profile, "platforms"):
                    raw_sources.append(getattr(profile, "platforms"))
        except Exception:
            pass
        finally:
            session.close()

    # 3. Anti-Corruption Layer: строгая валидация и нормализация через ActiveChannelsDTO
    collected_channels: List[str] = []
    for raw_data in raw_sources:
        try:
            dto = ActiveChannelsDTO(channels=raw_data)
            for ch in dto.channels:
                if ch not in collected_channels:
                    collected_channels.append(ch)
        except Exception:
            # Изолируем поврежденный источник и продолжаем валидацию остальных
            continue

    return collected_channels if collected_channels else ["telegram"]

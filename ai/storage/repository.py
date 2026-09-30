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
        ChannelRegistrationDTO,
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
        ChannelRegistrationDTO,
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
    Read Path (O(1) CPU Fast Path):
    Извлекает список активных каналов из БД / профиля.
    Использует строгий ActiveChannelsDTO (принимает исключительно канонический List[str]).
    Гарантирует детерминированный контракт List[str] с фоллбэком на ['telegram'].
    """
    raw_sources: List[Any] = []

    # 1. Проверка переданного словаря профиля
    if profile_data and isinstance(profile_data, dict):
        for key in ("connected_channels", "target_channels", "platforms"):
            val = profile_data.get(key)
            if val is not None:
                raw_sources.append(val)

    # 2. Извлечение из базы данных (Single Source of Truth: connected_channels JSONB)
    if not raw_sources and database and user_id:
        session = database.get_session()
        try:
            query = session.query(UserProfile)
            if str(user_id).isdigit():
                profile = query.filter(or_(UserProfile.external_user_id == str(user_id), UserProfile.id == int(user_id))).first()
            else:
                profile = query.filter(UserProfile.external_user_id == str(user_id)).first()

            if profile and hasattr(profile, "connected_channels") and profile.connected_channels:
                raw_sources.append(profile.connected_channels)
        except Exception:
            pass
        finally:
            session.close()

    # 3. Строгая O(1) валидация через ActiveChannelsDTO (Read Path)
    collected_channels: List[str] = []
    for raw_data in raw_sources:
        try:
            dto = ActiveChannelsDTO(channels=raw_data)
            for ch in dto.channels:
                if ch not in collected_channels:
                    collected_channels.append(ch)
        except Exception:
            continue

    return collected_channels if collected_channels else ["telegram"]


def save_user_connected_channels(
    database: Database,
    user_id: str,
    raw_channels: Any
) -> List[str]:
    """
    Write Path (Shift-Left Validation):
    Принимает пользовательские входные данные (алиасы, URL, флаги),
    нормализует через ChannelRegistrationDTO и записывает в БД
    чистый канонический массив JSONB List[str].
    """
    # 1. Shift-Left нормализация на границе записи
    write_dto = ChannelRegistrationDTO(channels=raw_channels)
    canonical_channels = write_dto.channels if write_dto.channels else ["telegram"]

    # 2. Запись в БД
    session = database.get_session()
    try:
        query = session.query(UserProfile)
        if str(user_id).isdigit():
            profile = query.filter(or_(UserProfile.external_user_id == str(user_id), UserProfile.id == int(user_id))).first()
        else:
            profile = query.filter(UserProfile.external_user_id == str(user_id)).first()

        if profile:
            profile.connected_channels = canonical_channels
            profile.social_links = {ch: True for ch in canonical_channels}
            session.commit()
            return canonical_channels
        else:
            # Создаем профиль с каноническими каналами, если не найден
            new_profile = UserProfile(
                external_user_id=str(user_id),
                connected_channels=canonical_channels,
                social_links={ch: True for ch in canonical_channels}
            )
            session.add(new_profile)
            session.commit()
            return canonical_channels
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

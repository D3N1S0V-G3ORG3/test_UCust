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
    Извлекает список только реально подключенных и активных каналов (is_active=True):
    1. Проверяет переданный profile_data (connected_channels / platforms / social_links).
    2. Если данных нет, запрашивает UserProfile / ProjectMetadata из базы данных.
    3. Возвращает список идентификаторов каналов (например: ['telegram', 'vk']).
    4. По умолчанию возвращает ['telegram'].
    """
    active_channels: List[str] = []

    # 1. Анализ переданного словаря профиля
    if profile_data:
        # Прямой список target_channels
        if "target_channels" in profile_data and isinstance(profile_data["target_channels"], list):
            return [c.lower() for c in profile_data["target_channels"] if c]

        # Словарь connected_channels
        cc = profile_data.get("connected_channels") or profile_data.get("social_networks")
        if isinstance(cc, dict):
            for ch_name, ch_info in cc.items():
                if isinstance(ch_info, dict) and ch_info.get("is_active", True):
                    active_channels.append(ch_name.lower())
                elif isinstance(ch_info, bool) and ch_info:
                    active_channels.append(ch_name.lower())

        # Поле platforms в проекте
        platforms = profile_data.get("platforms")
        if isinstance(platforms, list):
            for p in platforms:
                if isinstance(p, str) and p.lower() not in active_channels:
                    active_channels.append(p.lower())
        elif isinstance(platforms, dict):
            for p_name, p_val in platforms.items():
                if p_val and p_name.lower() not in active_channels:
                    active_channels.append(p_name.lower())

        # social_links из анкеты
        social_links = profile_data.get("social_links")
        if isinstance(social_links, dict):
            for s_name, s_val in social_links.items():
                if s_val and s_name.lower() not in active_channels:
                    # Нормализуем имена каналов
                    norm_name = s_name.lower()
                    if norm_name in ["tg", "telegram", "телеграм"]:
                        active_channels.append("telegram")
                    elif norm_name in ["vk", "vkontakte", "вк", "вконтакте"]:
                        active_channels.append("vk")
                    elif norm_name in ["ok", "odnoklassniki", "ок", "одноклассники"]:
                        active_channels.append("ok")
                    elif norm_name in ["max", "messenger", "max_messenger", "мессенджер"]:
                        active_channels.append("max_messenger")

    # 2. Запрос к базе данных, если список пуст
    if not active_channels and database and user_id:
        session = database.get_session()
        try:
            query = session.query(UserProfile)
            if str(user_id).isdigit():
                profile = query.filter(or_(UserProfile.external_user_id == str(user_id), UserProfile.id == int(user_id))).first()
            else:
                profile = query.filter(UserProfile.external_user_id == str(user_id)).first()

            if profile and profile.social_links:
                for s_name, s_val in profile.social_links.items():
                    if s_val:
                        norm_name = s_name.lower()
                        if norm_name in ["tg", "telegram"] and "telegram" not in active_channels:
                            active_channels.append("telegram")
                        elif norm_name in ["vk", "vkontakte"] and "vk" not in active_channels:
                            active_channels.append("vk")
                        elif norm_name in ["ok", "odnoklassniki"] and "ok" not in active_channels:
                            active_channels.append("ok")
                        elif norm_name in ["max", "messenger", "max_messenger"] and "max_messenger" not in active_channels:
                            active_channels.append("max_messenger")
        except Exception:
            pass
        finally:
            session.close()

    # Дедупликация и фоллбэк
    clean_channels = list(dict.fromkeys(active_channels))
    return clean_channels if clean_channels else ["telegram"]

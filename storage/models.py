"""
SQLAlchemy-модели для хранения анкеты, проектов и истории публикаций.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import relationship

from .db import Base


class UserProfile(Base):
    """
    ORM-модель анкеты пользователя из 5 шагов.

    Содержит сериализованные данные анкеты, которые далее используются
    аналитическим агентом и нейросетевым генеративным модулем.
    """

    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True)
    external_user_id = Column(String(64), nullable=True, index=True)
    step1 = Column(JSON, nullable=False)
    step2 = Column(JSON, nullable=False)
    step3 = Column(JSON, nullable=False)
    step4 = Column(JSON, nullable=False)
    step5 = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    projects = relationship("ProjectMetadata", back_populates="user_profile")
    content_tasks = relationship("ContentTask", back_populates="user_profile")


class ProjectMetadata(Base):
    """
    ORM-модель метаданных проекта.

    Описывает ключевые параметры SMM-проекта и связь с анкетой пользователя.
    """

    __tablename__ = "project_metadata"

    id = Column(Integer, primary_key=True)
    user_profile_id = Column(Integer, ForeignKey("user_profiles.id"), nullable=False)
    name = Column(String(256), nullable=False)
    niche = Column(String(128), nullable=False)
    platforms = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user_profile = relationship("UserProfile", back_populates="projects")
    publications = relationship("PublicationHistory", back_populates="project")


class PublicationHistory(Base):
    """
    ORM-модель истории публикаций.

    Хранит тексты, статусы и метаданные, которые необходимы для контроля
    уникальности контента и исключения дублей в рамках одной ниши.
    """

    __tablename__ = "publication_history"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("project_metadata.id"), nullable=False)
    platform = Column(String(64), nullable=False)
    post_text = Column(Text, nullable=False)
    status = Column(String(64), nullable=False)
    extra_metadata = Column("metadata", JSON, nullable=True)
    published_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("ProjectMetadata", back_populates="publications")


class ContentTask(Base):
    """
    ORM-модель задачи контентного конвейера.

    Хранит статус выполнения цепочки агентов и ошибки при обработке.
    """

    __tablename__ = "content_tasks"

    id = Column(Integer, primary_key=True)
    user_profile_id = Column(Integer, ForeignKey("user_profiles.id"), nullable=False)
    status = Column(String(32), nullable=False, index=True)
    error_message = Column(Text, nullable=True)
    result_payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user_profile = relationship("UserProfile", back_populates="content_tasks")

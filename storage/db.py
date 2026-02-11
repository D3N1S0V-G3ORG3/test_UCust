"""
Модуль работы с SQL базой данных (PostgreSQL).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session


Base = declarative_base()


class Database:
    """
    Менеджер подключения к SQL-хранилищу.

    Используется агентами для сохранения данных анкеты и истории публикаций.
    """

    def __init__(self, dsn: str) -> None:
        """
        Инициализирует движок и фабрику сессий.

        :param dsn: строка подключения к PostgreSQL.
        """

        self._engine = create_engine(dsn, echo=False, future=True)
        self._session_factory = sessionmaker(bind=self._engine, class_=Session, autoflush=False)

    def create_all(self) -> None:
        """
        Создает все таблицы в SQL-хранилище.

        Используется при первичном развертывании комплекса.
        """

        Base.metadata.create_all(self._engine)

    def get_session(self) -> Session:
        """
        Возвращает новую сессию SQLAlchemy для операций чтения/записи.
        """

        return self._session_factory()


class DatabaseFactory:
    """
    Фабрика подключения с конфигурацией по умолчанию.

    Используется, когда требуется быстро подключить модуль хранения
    без ручной настройки параметров.
    """

    DEFAULT_DSN = "postgresql+psycopg2://user:password@localhost:5432/ai_smm"

    @classmethod
    def build(cls, dsn: Optional[str] = None) -> Database:
        """
        Создает экземпляр Database с указанным или дефолтным DSN.
        """

        return Database(dsn or cls.DEFAULT_DSN)

"""
SQLAlchemy v2.0 Async Database Manager and CRUD operations for UCust.AI.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, Optional

try:
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
    from sqlalchemy.ext.asyncio import (
        AsyncEngine,
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
    class Base(DeclarativeBase):
        """Base class for all SQLAlchemy v2.0 declarative models."""
        pass
except (ImportError, Exception):
    create_engine = None
    select = None
    DeclarativeBase = object
    Session = Any
    sessionmaker = Any
    create_async_engine = None
    AsyncEngine = Any
    AsyncSession = Any
    async_sessionmaker = Any

    class _MockMetadata:
        def create_all(self, *args, **kwargs):
            pass
        def drop_all(self, *args, **kwargs):
            pass

    class Base:
        metadata = _MockMetadata()


# Database URL from environment variable
DEFAULT_DB_URL = "postgresql+asyncpg://user:password@localhost:5432/ai_smm"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DB_URL)

logger = logging.getLogger("storage.db")
_db_engine = None


def get_async_engine():
    """
    Returns or creates the global database engine.
    Uses AsyncEngine when PostgreSQL/asyncpg is configured;
    falls back to SQLite engine wrapped via asyncio for local dev & testing.
    """
    global _db_engine
    if _db_engine is None:
        raw_url = os.getenv("DATABASE_URL", DEFAULT_DB_URL)
        if create_async_engine is not None and "asyncpg" in raw_url:
            try:
                _db_engine = create_async_engine(raw_url, echo=False, future=True)
                logger.info("Created AsyncEngine for PostgreSQL (%s)", raw_url.split("@")[-1])
                return _db_engine
            except Exception as exc:
                logger.warning("AsyncEngine creation failed for '%s': %s", raw_url, exc)

        fallback_url = "sqlite:///./ai_smm_dev.db"
        _db_engine = create_engine(fallback_url, echo=False, future=True)
        logger.info("Created SQLite Fallback Engine (%s)", fallback_url)
    return _db_engine


def get_async_sessionmaker():
    """Returns an async sessionmaker or standard sessionmaker."""
    engine = get_async_engine()
    if isinstance(engine, AsyncEngine):
        return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False, autoflush=False)


async def get_db_session() -> AsyncGenerator[Any, None]:
    """
    FastAPI Dependency Injection provider for database session.
    Usage in route: session = Depends(get_db_session)
    """
    engine = get_async_engine()
    if isinstance(engine, AsyncEngine):
        session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
    else:
        SessionMaker = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
        with SessionMaker() as session:
            try:
                yield session
            finally:
                session.close()


async def init_db(engine: Any = None) -> None:
    """
    Initializes database tables asynchronously.
    Should be called on FastAPI startup event or lifespan.
    """
    global _db_engine
    target_engine = engine or get_async_engine()

    if isinstance(target_engine, AsyncEngine):
        try:
            async with target_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables initialized via AsyncEngine.")
            return
        except Exception as exc:
            logger.warning("PostgreSQL connection unreached: %s. Using SQLite fallback.", exc)
            fallback_url = "sqlite:///./ai_smm_dev.db"
            _db_engine = create_engine(fallback_url, echo=False, future=True)
            target_engine = _db_engine

    def sync_init():
        sync_eng = target_engine.sync_engine if isinstance(target_engine, AsyncEngine) else target_engine
        Base.metadata.create_all(bind=sync_eng)
        # Автоматическая миграция недостающих колонок для SQLite/PostgreSQL
        try:
            from sqlalchemy import inspect, text
            inspector = inspect(sync_eng)
            if "user_profiles" in inspector.get_table_names():
                cols = {c["name"] for c in inspector.get_columns("user_profiles")}
                with sync_eng.connect() as conn:
                    if "company_name" not in cols:
                        conn.execute(text("ALTER TABLE user_profiles ADD COLUMN company_name VARCHAR(256)"))
                        conn.commit()
                        logger.info("Auto-migrated schema: added 'company_name' to user_profiles")
                    if "social_links" not in cols:
                        conn.execute(text("ALTER TABLE user_profiles ADD COLUMN social_links JSON"))
                        conn.commit()
                    if "visual_grid_dna" not in cols:
                        conn.execute(text("ALTER TABLE user_profiles ADD COLUMN visual_grid_dna JSON"))
                        conn.commit()
                    if "brand_dossier" not in cols:
                        conn.execute(text("ALTER TABLE user_profiles ADD COLUMN brand_dossier JSON"))
                        conn.commit()
        except Exception as mig_err:
            logger.debug("Schema inspection/migration notice: %s", mig_err)

    await asyncio.to_thread(sync_init)
    logger.info("Database tables initialized successfully via init_db().")


async def create_task(
    user_id: str,
    user_profile_id: Optional[int] = None,
    status: str = "PENDING",
    session: Any = None,
) -> int:
    from storage.models import ContentTask
    """
    Creates a new ContentTask in DB asynchronously and returns job_id (task.id).

    :param user_id: External user identifier.
    :param user_profile_id: Optional FK reference to UserProfile.
    :param status: Initial task status (defaults to "PENDING").
    :param session: Optional existing session instance.
    :return: Generated job_id (task.id).
    """
    if AsyncSession is not None and isinstance(session, AsyncSession):
        task = ContentTask(
            user_id=user_id,
            user_profile_id=user_profile_id,
            status=status,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        return task.id

    def sync_create() -> int:
        eng = get_async_engine()
        if hasattr(session, "add"):
            task = ContentTask(
                user_id=user_id,
                user_profile_id=user_profile_id,
                status=status,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(task)
            session.commit()
            session.refresh(task)
            return task.id

        SessionMaker = sessionmaker(bind=eng, class_=Session, expire_on_commit=False)
        with SessionMaker() as s:
            task = ContentTask(
                user_id=user_id,
                user_profile_id=user_profile_id,
                status=status,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            s.add(task)
            s.commit()
            s.refresh(task)
            return task.id

    return await asyncio.to_thread(sync_create)


async def update_task_status(
    job_id: int,
    status: str,
    result_payload: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
    session: Any = None,
) -> None:
    from storage.models import ContentTask
    """
    Updates ContentTask status and payload in DB asynchronously.

    :param job_id: Unique task identifier.
    :param status: Updated FSM task status.
    :param result_payload: Optional result payload dict (stored in post_draft_json).
    :param error_message: Optional error message string.
    :param session: Optional existing session instance.
    """
    if AsyncSession is not None and isinstance(session, AsyncSession):
        stmt = select(ContentTask).where(ContentTask.id == job_id)
        res = await session.execute(stmt)
        task = res.scalar_one_or_none()
        if task is not None:
            task.status = status
            if result_payload is not None:
                task.post_draft_json = result_payload
            if error_message is not None:
                task.error_message = error_message
            task.updated_at = datetime.utcnow()
            await session.commit()
        return

    def sync_update() -> None:
        if hasattr(session, "query"):
            task = session.query(ContentTask).filter(ContentTask.id == job_id).first()
            if task is not None:
                task.status = status
                if result_payload is not None:
                    task.post_draft_json = result_payload
                if error_message is not None:
                    task.error_message = error_message
                task.updated_at = datetime.utcnow()
                session.commit()
            return

        eng = get_async_engine()
        SessionMaker = sessionmaker(bind=eng, class_=Session, expire_on_commit=False)
        with SessionMaker() as s:
            task = s.query(ContentTask).filter(ContentTask.id == job_id).first()
            if task is None:
                logger.warning("update_task_status: Task job_id=%d not found.", job_id)
                return
            task.status = status
            if result_payload is not None:
                task.post_draft_json = result_payload
            if error_message is not None:
                task.error_message = error_message
            task.updated_at = datetime.utcnow()
            s.commit()

    await asyncio.to_thread(sync_update)


async def get_task(
    job_id: int,
    session: Any = None,
) -> Optional[Any]:
    from storage.models import ContentTask
    """
    Retrieves ContentTask by job_id asynchronously.

    :param job_id: Unique task identifier.
    :param session: Optional existing session instance.
    :return: ContentTask ORM instance or None.
    """
    if AsyncSession is not None and isinstance(session, AsyncSession):
        stmt = select(ContentTask).where(ContentTask.id == job_id)
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    def sync_get() -> Optional[Any]:
        if hasattr(session, "query"):
            return session.query(ContentTask).filter(ContentTask.id == job_id).first()

        eng = get_async_engine()
        SessionMaker = sessionmaker(bind=eng, class_=Session, expire_on_commit=False)
        with SessionMaker() as s:
            return s.query(ContentTask).filter(ContentTask.id == job_id).first()

    return await asyncio.to_thread(sync_get)


async def get_pending_tasks(
    session: Any = None,
) -> List[Any]:
    from storage.models import ContentTask
    """
    Retrieves all ContentTasks with status 'AWAITING_USER_ACTION' or 'AWAITING_USER_DECISION'.
    """
    pending_statuses = ["AWAITING_USER_ACTION", "AWAITING_USER_DECISION"]
    if AsyncSession is not None and isinstance(session, AsyncSession):
        stmt = select(ContentTask).where(ContentTask.status.in_(pending_statuses))
        res = await session.execute(stmt)
        return list(res.scalars().all())

    def sync_get_pending() -> List[ContentTask]:
        if hasattr(session, "query"):
            return session.query(ContentTask).filter(ContentTask.status.in_(pending_statuses)).all()

        eng = get_async_engine()
        SessionMaker = sessionmaker(bind=eng, class_=Session, expire_on_commit=False)
        with SessionMaker() as s:
            return s.query(ContentTask).filter(ContentTask.status.in_(pending_statuses)).all()

    return await asyncio.to_thread(sync_get_pending)


# Legacy synchronous Database class compatibility wrapper
class Database:
    """Synchronous compatibility wrapper for legacy callers."""

    def __init__(self, dsn: Optional[str] = None) -> None:
        raw_url = dsn or DATABASE_URL
        sync_url = raw_url.replace("+asyncpg", "").replace("+aiosqlite", "")
        try:
            self._engine = create_engine(sync_url, echo=False, future=True)
        except Exception:
            self._engine = create_engine("sqlite:///./ai_smm_dev.db", echo=False, future=True)

        self._session_factory = sessionmaker(bind=self._engine, class_=Session, autoflush=False)

    def create_all(self) -> None:
        try:
            Base.metadata.create_all(bind=self._engine)
            from sqlalchemy import inspect, text
            inspector = inspect(self._engine)
            if "user_profiles" in inspector.get_table_names():
                cols = {c["name"] for c in inspector.get_columns("user_profiles")}
                with self._engine.connect() as conn:
                    if "company_name" not in cols:
                        conn.execute(text("ALTER TABLE user_profiles ADD COLUMN company_name VARCHAR(256)"))
                    if "social_links" not in cols:
                        conn.execute(text("ALTER TABLE user_profiles ADD COLUMN social_links JSON"))
                    if "visual_grid_dna" not in cols:
                        conn.execute(text("ALTER TABLE user_profiles ADD COLUMN visual_grid_dna JSON"))
                    if "brand_dossier" not in cols:
                        conn.execute(text("ALTER TABLE user_profiles ADD COLUMN brand_dossier JSON"))
                    conn.commit()
        except Exception:
            pass

    def get_session(self) -> Session:
        return self._session_factory()


class DatabaseFactory:
    """Factory wrapper for Database."""

    @classmethod
    def build(cls, dsn: Optional[str] = None) -> Database:
        return Database(dsn)


__all__ = [
    "Base",
    "Database",
    "DatabaseFactory",
    "get_async_engine",
    "get_async_sessionmaker",
    "get_db_session",
    "init_db",
    "create_task",
    "update_task_status",
    "get_task",
    "get_pending_tasks",
]

"""
File: ai/core/database.py
Асинхронное подключение и инициализация базы данных (PostgreSQL pgvector / SQLite fallback).
"""

from __future__ import annotations

import os
import logging
try:
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy import text
    from sqlalchemy.orm import declarative_base
    Base = declarative_base()
except (ImportError, Exception):
    create_async_engine = None
    async_sessionmaker = None
    AsyncSession = None
    text = lambda x: x
    class _MockMetadata:
        def create_all(self, *args, **kwargs):
            pass
        def drop_all(self, *args, **kwargs):
            pass
    class Base:
        metadata = _MockMetadata()

logger = logging.getLogger("Database")

# Фоллбек на SQLite для локального тестирования
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./ucust_local_dev.db")
IS_POSTGRES = DATABASE_URL.startswith("postgresql")

if create_async_engine is not None:
    try:
        engine = create_async_engine(DATABASE_URL, echo=False)
        AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    except Exception:
        engine = None
        AsyncSessionLocal = None
else:
    engine = None
    AsyncSessionLocal = None


async def init_db():
    async with engine.begin() as conn:
        if IS_POSTGRES:
            try:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            except Exception as e:
                logger.warning(f"⚠️ Ошибка инициализации расширения pgvector: {e}")
        await conn.run_sync(Base.metadata.create_all)
    logger.info(f"✅ База данных инициализирована. Режим PostgreSQL: {IS_POSTGRES}")

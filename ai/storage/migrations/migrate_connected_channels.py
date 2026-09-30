"""
File: ai/storage/migrations/migrate_connected_channels.py
Одноразовая миграция схемы данных: приведение connected_channels и platforms
к строгому каноническому формату JSONB: ["telegram", "vk", "max_messenger"].

Запуск:
    python ai/storage/migrations/migrate_connected_channels.py
"""

from __future__ import annotations

import logging
import sys
from typing import Optional, List, Dict, Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ChannelMigration")

try:
    from schemas.models import ChannelRegistrationDTO, ActiveChannelsDTO
    from storage.db import Database
    from storage.models import UserProfile, ProjectMetadata
except ImportError:
    try:
        from ai.schemas.models import ChannelRegistrationDTO, ActiveChannelsDTO
        from ai.storage.db import Database
        from ai.storage.models import UserProfile, ProjectMetadata
    except ImportError:
        pass


# PostgreSQL DDL / DML скрипт для прямой миграции в СУБД (Alembic / psql)
POSTGRES_MIGRATION_SQL = """
-- 1. Добавление колонки connected_channels в таблицу user_profiles, если отсутствует
ALTER TABLE user_profiles 
ADD COLUMN IF NOT EXISTS connected_channels JSONB DEFAULT '["telegram"]'::jsonb;

-- 2. Индексация для O(1) поиска пользователей по активным соцсетям (GIN Index)
CREATE INDEX IF NOT EXISTS idx_user_profiles_connected_channels_gin 
ON user_profiles USING gin (connected_channels);

-- 3. Пример трансформации legacy social_links -> connected_channels
-- UPDATE user_profiles
-- SET connected_channels = (
--     SELECT jsonb_agg(DISTINCT lower(key))
--     FROM jsonb_each_text(COALESCE(social_links, '{}'::jsonb))
--     WHERE value IS NOT NULL AND value != '' AND value != 'false'
-- )
-- WHERE connected_channels IS NULL OR connected_channels = '[]'::jsonb;
"""


def migrate_connected_channels(database: Database) -> Dict[str, int]:
    """
    Выполняет проход по всем профилям и проектам в БД:
    1. Извлекает legacy social_links / platforms.
    2. Выполняет Shift-Left канонизацию через ChannelRegistrationDTO.
    3. Сохраняет строгий JSON-массив строк ['telegram', 'vk', ...] в connected_channels.
    4. Верифицирует результат через строгий ActiveChannelsDTO.
    """
    session = database.get_session()
    migrated_profiles_count = 0
    migrated_projects_count = 0
    errors_count = 0

    try:
        profiles = session.query(UserProfile).all()
        logger.info(f"🔄 Начало миграции каналов для {len(profiles)} профилей...")

        for prof in profiles:
            raw_data = None
            if hasattr(prof, "connected_channels") and prof.connected_channels:
                raw_data = prof.connected_channels
            elif prof.social_links:
                raw_data = prof.social_links

            try:
                # 1. Канонизация через Shift-Left DTO
                write_dto = ChannelRegistrationDTO(channels=raw_data if raw_data is not None else ["telegram"])
                canonical_channels = write_dto.channels if write_dto.channels else ["telegram"]

                # 2. Верификация через строгий Read DTO
                read_dto = ActiveChannelsDTO(channels=canonical_channels)

                # 3. Сохранение в БД в едином каноническом формате
                prof.connected_channels = read_dto.channels
                prof.social_links = {ch: True for ch in read_dto.channels}
                migrated_profiles_count += 1
            except Exception as exc:
                logger.error(f"❌ Ошибка миграции профиля id={prof.id}: {exc}")
                errors_count += 1

        projects = session.query(ProjectMetadata).all()
        logger.info(f"🔄 Начало миграции платформ для {len(projects)} проектов...")

        for proj in projects:
            try:
                write_dto = ChannelRegistrationDTO(channels=proj.platforms)
                canonical_channels = write_dto.channels if write_dto.channels else ["telegram"]
                proj.platforms = canonical_channels
                migrated_projects_count += 1
            except Exception as exc:
                logger.error(f"❌ Ошибка миграции проекта id={proj.id}: {exc}")
                errors_count += 1

        session.commit()
        logger.info(f"✅ Миграция успешно завершена! Профилей: {migrated_profiles_count}, Проектов: {migrated_projects_count}, Ошибок: {errors_count}")
        return {
            "migrated_profiles": migrated_profiles_count,
            "migrated_projects": migrated_projects_count,
            "errors": errors_count
        }
    except Exception as exc:
        session.rollback()
        logger.critical(f"💥 Критический сбой миграции: {exc}", exc_info=True)
        raise
    finally:
        session.close()


if __name__ == "__main__":
    db = Database()
    res = migrate_connected_channels(db)
    print("Migration result:", res)

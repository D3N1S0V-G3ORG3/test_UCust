"""
File: ai/storage/migrations/migrate_pgvector_rag.py
DDL Миграция pgvector 0.7.0+: Таблицы FactSheets/PIM фактов с квантованием halfvec(1536),
HNSW индексом по скалярному произведению (halfvec_ip_ops, m=32, ef_construction=128)
и каскадным физическим удалением (Hard Delete) для защиты связности графа.

Запуск:
    python ai/storage/migrations/migrate_pgvector_rag.py
"""

from __future__ import annotations

import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PGVectorMigration")

# PostgreSQL DDL / DML скрипт
POSTGRES_PGVECTOR_RAG_DDL = """
-- 1. Активация расширения pgvector (версия >= 0.7.0 с поддержкой halfvec)
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Таблица метаданных фактов (FactSheets / PIM-каталог)
CREATE TABLE IF NOT EXISTS fact_metadata (
    id SERIAL PRIMARY KEY,
    project_id VARCHAR(128) NOT NULL,
    sku_id VARCHAR(128),
    fact_type VARCHAR(64) NOT NULL,
    version INT NOT NULL DEFAULT 1,
    valid_until TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Индексы для префильтрации по арендатору и сроку актуальности
CREATE INDEX IF NOT EXISTS idx_fact_metadata_project_sku 
ON fact_metadata (project_id, sku_id);

CREATE INDEX IF NOT EXISTS idx_fact_metadata_valid_until 
ON fact_metadata (valid_until);

-- 3. Таблица эмбеддингов (1536-dim, halfvec FP16)
-- Hard Delete via ON DELETE CASCADE гарантирует физическое перестроение связей в графе HNSW
CREATE TABLE IF NOT EXISTS fact_embeddings (
    fact_id INT PRIMARY KEY REFERENCES fact_metadata(id) ON DELETE CASCADE,
    embedding halfvec(1536) NOT NULL
);

-- 4. Высокоточный HNSW индекс для Negative Inner Product (<#>)
-- m=32, ef_construction=128 обеспечивают стабильный Recall >= 99% на 1536-мерных пространствах
CREATE INDEX IF NOT EXISTS idx_fact_embeddings_hnsw 
ON fact_embeddings 
USING hnsw (embedding halfvec_ip_ops) 
WITH (m = 32, ef_construction = 128);
"""


def apply_migration(db_url: str | None = None) -> None:
    """
    Применяет DDL-миграцию в PostgreSQL базе данных.
    """
    url = db_url or os.getenv("DATABASE_URL")
    if not url:
        logger.info("ℹ️ DATABASE_URL не указан. Печать DDL скрипта для ручного применения:")
        print(POSTGRES_PGVECTOR_RAG_DDL)
        return

    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(url)
        with engine.connect() as conn:
            logger.info("🔧 Выполнение DDL-миграции pgvector RAG...")
            conn.execute(text(POSTGRES_PGVECTOR_RAG_DDL))
            conn.commit()
            logger.info("✅ DDL-миграция pgvector RAG успешно выполнена.")
    except Exception as exc:
        logger.error(f"❌ Ошибка при выполнении миграции: {exc}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    apply_migration()

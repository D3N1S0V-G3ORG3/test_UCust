"""
Скрипт для быстрой проверки состояния RAG-системы и базы пользователей UCust AI.
Поддерживает как SQLite fallback, так и PostgreSQL/pgvector.

Использование на сервере:
    cd /opt/ucust/ai
    source venv/bin/activate
    python scripts/inspect_rag_and_users.py
"""

from __future__ import annotations

import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import json

# Загружаем переменные из .env
def load_env_candidates():
    paths = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"),
        "/opt/ucust/ai/.env",
        "/opt/ucust/.env",
        ".env"
    ]
    for p in paths:
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            except Exception:
                pass

load_env_candidates()

# Добавляем пути импорта
current_dir = os.path.dirname(os.path.abspath(__file__))
ai_dir = os.path.dirname(current_dir)
if ai_dir not in sys.path:
    sys.path.insert(0, ai_dir)

from sqlalchemy import create_engine, inspect, text
from storage.db import DATABASE_URL, get_async_engine

def print_header(title: str):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)

def find_working_engine():
    # Собираем список кандидатов подключения
    candidates = []
    
    # 1. Из окружения
    env_db = os.getenv("DATABASE_URL")
    if env_db:
        candidates.append(("DATABASE_URL из .env", env_db.replace("+asyncpg", "").replace("+aiosqlite", "")))
        
    # 2. Из POSTGRES_* переменных
    pg_user = os.getenv("POSTGRES_USER", "postgres")
    pg_pass = os.getenv("POSTGRES_PASSWORD", "postgres")
    pg_host = os.getenv("POSTGRES_HOST", "localhost")
    pg_port = os.getenv("POSTGRES_PORT", "5432")
    pg_db = os.getenv("POSTGRES_DB", "ai_smm")
    candidates.append((
        f"PostgreSQL ({pg_user}@{pg_host}:{pg_port}/{pg_db})",
        f"postgresql://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"
    ))

    # 3. Дефолтный postgres:postgres
    candidates.append((
        "PostgreSQL (postgres:postgres@localhost:5432/ai_smm)",
        "postgresql://postgres:postgres@localhost:5432/ai_smm"
    ))

    # 4. Локальные SQLite базы данных
    sqlite_paths = [
        os.path.join(ai_dir, "ai_smm_dev.db"),
        os.path.join(os.path.dirname(ai_dir), "ai_smm_dev.db"),
        "/opt/ucust/ai/ai_smm_dev.db",
        "/opt/ucust/ai_smm_dev.db",
        "./ai_smm_dev.db"
    ]
    for sp in sqlite_paths:
        if os.path.isfile(sp):
            candidates.append((f"SQLite файл ({sp})", f"sqlite:///{sp}"))

    # Проверяем кандидатов
    for label, url in candidates:
        try:
            eng = create_engine(url, echo=False)
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            print(f"✅ Успешно подключено к: {label}")
            return eng, label, url
        except Exception as e:
            # Не шумим на известные ошибки авторизации или отсутствия сервера
            err_msg = str(e).split("\n")[0]
            print(f"❌ Не удалось подключиться к {label}: {err_msg[:80]}")

    # Fallback на дефолтный sqlite
    fallback = "sqlite:///./ai_smm_dev.db"
    print(f"🔄 Используем стандартный fallback: {fallback}")
    return create_engine(fallback, echo=False), "SQLite Default", fallback

def inspect_system():
    print_header("🔌 ПОДКЛЮЧЕНИЕ К БАЗЕ ДАННЫХ")
    engine, engine_label, engine_url = find_working_engine()

    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    print(f"Существующие таблицы: {', '.join(existing_tables) if existing_tables else 'нет'}")

    # =========================================================================
    # 1. ПОЛЬЗОВАТЕЛИ И ПРОФИЛИ (user_profiles)
    # =========================================================================
    print_header("👥 1. ПОЛЬЗОВАТЕЛИ И ПРОФИЛИ (Таблица: user_profiles)")
    if "user_profiles" in existing_tables:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM user_profiles ORDER BY id DESC")).fetchall()
            print(f"Всего пользователей / профилей в БД: {len(rows)}")
            
            for idx, r in enumerate(rows, 1):
                # Маппим поля словарем
                row_dict = dict(r._mapping) if hasattr(r, "_mapping") else dict(zip(inspector.get_columns("user_profiles"), r))
                user_id = row_dict.get("user_id") or row_dict.get("external_user_id") or f"ID_{row_dict.get('id')}"
                company = row_dict.get("company_name") or "Не указано"
                niche = row_dict.get("niche") or "Не указана"
                city = row_dict.get("city") or "Не указан"
                country = row_dict.get("country") or "Россия"
                ta = row_dict.get("target_audience") or "Не указана"
                created = row_dict.get("created_at") or "—"
                channels = row_dict.get("connected_channels") or []

                print(f"\n--- [Пользователь #{row_dict.get('id')}] ID: {user_id} ---")
                print(f"  🏢 Компания / Бренд : {company}")
                print(f"  🎯 Ниша              : {niche}")
                print(f"  📍 Локация           : {city}, {country}")
                print(f"  👥 Аудитория (ЦА)    : {ta}")
                print(f"  📢 Каналы            : {channels}")
                print(f"  🕒 Создан            : {created}")

                # Краткая сводка онбординга
                step1 = row_dict.get("step1")
                if isinstance(step1, str):
                    try: step1 = json.loads(step1)
                    except: pass
                if isinstance(step1, dict) and step1:
                    print(f"  ✨ Tone of Voice     : {step1.get('voice_and_tone', '—')}")
                    print(f"  🎨 Фирменные цвета   : {step1.get('brand_colors', '—')}")

                dossier = row_dict.get("brand_dossier")
                if isinstance(dossier, str):
                    try: dossier = json.loads(dossier)
                    except: pass
                if isinstance(dossier, dict) and dossier:
                    print(f"  📁 Досье бренда      : {list(dossier.keys())}")
    else:
        print("Таблица 'user_profiles' пока не создана.")

    # =========================================================================
    # 2. ПРОФИЛИ БРЕНДОВ В RAG (brand_profiles)
    # =========================================================================
    print_header("🏷️ 2. ПРОФИЛИ В RAG (Таблица: brand_profiles)")
    if "brand_profiles" in existing_tables:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM brand_profiles")).fetchall()
            print(f"Всего Brand DNA профилей в RAG: {len(rows)}")
            for r in rows:
                row_dict = dict(r._mapping)
                print(f"\n  Tenant ID: {row_dict.get('tenant_id')}")
                print(f"  Компания : {row_dict.get('company_name')}")
                print(f"  Индустрия: {row_dict.get('industry_type')}")
                print(f"  Тональность: {row_dict.get('tone_of_voice')}")
    else:
        print("Таблица 'brand_profiles' пока не создана.")

    # =========================================================================
    # 3. ВЕКТОРНЫЕ ЧАНКИ ЗНАНИЙ (tenant_knowledge_chunks / fact_metadata)
    # =========================================================================
    print_header("📚 3. ЧАНКИ ЗНАНИЙ RAG (Таблицы: tenant_knowledge_chunks / fact_metadata)")
    if "tenant_knowledge_chunks" in existing_tables:
        with engine.connect() as conn:
            count = conn.execute(text("SELECT count(*) FROM tenant_knowledge_chunks")).scalar()
            print(f"Всего фрагментов в tenant_knowledge_chunks: {count}")
            sample_rows = conn.execute(text("SELECT chunk_id, tenant_id, source_type, content FROM tenant_knowledge_chunks LIMIT 5")).fetchall()
            if sample_rows:
                print("\nПримеры сохраненных чанков:")
                for r in sample_rows:
                    row_dict = dict(r._mapping)
                    snippet = row_dict.get("content", "")[:120].replace("\n", " ")
                    print(f"  • [{row_dict.get('tenant_id')}] ({row_dict.get('source_type')}): \"{snippet}...\"")
    elif "fact_metadata" in existing_tables:
        with engine.connect() as conn:
            count = conn.execute(text("SELECT count(*) FROM fact_metadata")).scalar()
            print(f"Всего фактов/чанков в fact_metadata: {count}")
            sample_rows = conn.execute(text("SELECT * FROM fact_metadata LIMIT 5")).fetchall()
            if sample_rows:
                print("\nПримеры фактов:")
                for r in sample_rows:
                    row_dict = dict(r._mapping)
                    print(f"  • {row_dict}")
    else:
        print("Таблицы базы знаний пока не содержат данных.")

    # =========================================================================
    # 4. ЛОКАЛЬНЫЙ РАГ-ПАЙПЛАЙН (Тестовый семантический поиск)
    # =========================================================================
    print_header("🔍 4. ТЕСТ СЕМАНТИЧЕСКОГО ПОИСКА CLEAN RAG")
    try:
        from rag.pipeline import CleanRAGPipeline
        rag = CleanRAGPipeline(min_confidence_threshold=0.40)
        query = "кофе меню цены доставка"
        res = rag.query(query)
        print(f"Тестовый запрос: '{query}'")
        print(f"Достаточный контекст: {res.has_sufficient_context} (Top score: {round(res.top_score, 3)})")
        if res.chunks:
            print(f"Найдено релевантных чанков: {len(res.chunks)}")
            for c in res.chunks[:3]:
                print(f"  - [{c.source}] score={round(c.confidence_score, 3)}: {c.text[:80]}...")
        else:
            print("  (База знаний в памяти пока пуста)")
    except Exception as e:
        print(f"  Ошибка вызова CleanRAGPipeline: {e}")

    print("\n" + "=" * 70 + "\n")

if __name__ == "__main__":
    inspect_system()

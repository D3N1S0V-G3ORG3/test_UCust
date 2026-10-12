"""
Скрипт создания базы знаний и профиля для UCust AI (Self-Promoting Agent).
Обучает систему писать посты о себе: своих агентах, фичах, преимуществах,
тарифах, кейсах и конверсионной воронке.

Использование на сервере:
    cd /opt/ucust/ai
    source venv/bin/activate
    python scripts/seed_ucust_brand_knowledge.py
"""

from __future__ import annotations

import os
import sys
import json
import uuid

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Добавляем пути импорта
current_dir = os.path.dirname(os.path.abspath(__file__))
ai_dir = os.path.dirname(current_dir)
if ai_dir not in sys.path:
    sys.path.insert(0, ai_dir)

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from storage.db import DATABASE_URL, get_async_engine
from storage.models import UserProfile, Base as StorageBase
from models.db_models import BrandProfileModel, TenantKnowledgeChunk, Base as RAGBase

TENANT_ID = "ucust_ai"
COMPANY_NAME = "UCust AI"

# -----------------------------------------------------------------------------
# 1. СТРУКТУРИРОВАННАЯ БАЗА ЗНАНИЙ UCUST AI (RAG CHUNKS)
# -----------------------------------------------------------------------------
UCUST_KNOWLEDGE_DOCS = [
    {
        "id": "ucust_overview",
        "source": "architecture",
        "title": "О платформе UCust AI",
        "content": (
            "UCust AI — это автономная мультиагентная платформа для генерации коммерческого контента и ведения соцсетей. "
            "Вместо одного чат-бота здесь работает слаженная команда специализированных ИИ-агентов: "
            "Шеф-Оркестратор, Аналитик онбординга, Копирайтеры соцсетей (Telegram, VK, OK, MAX), "
            "Критик фактологии Чарли Мангера и Фотогенератор на базе ComfyUI Qwen-Image 2512. "
            "Платформа полностью берет на себя рутину SMM: от сбора данных о бренде за 60 секунд до публикации готовых постов с визуалом."
        )
    },
    {
        "id": "ucust_multichannel_formatting",
        "source": "features",
        "title": "Нативное богатое форматирование каналов",
        "content": (
            "UCust AI нативно адаптирует контент под стандарты каждой социальной сети: "
            "1. Telegram 7.2+: скрытые интриги под спойлерами <tg-spoiler>, сворачиваемые рецепты, цитаты и прайс-листы <blockquote expandable>, "
            "кликабельные промокоды <code>, зачеркнутые старые цены <s> и интерактивные инлайн-кнопки для мгновенного заказа. "
            "2. ВКонтакте: строгое соблюдение правила ката (280 символов) — главный хук и оффер помещаются до кнопки 'Показать полностью...', "
            "структурированные буллеты без каши и внешние ссылки в первом комментарии для защиты органических охватов. "
            "3. MAX Messenger: лаконичные push-сообщения (до 350 символов) с ключевой сутью в первых 50 символах для экрана блокировки."
        )
    },
    {
        "id": "ucust_smart_idea_bank",
        "source": "features",
        "title": "Интеллектуальный Банк Идей (Smart Idea Bank)",
        "content": (
            "Банк Идей UCust AI решает проблему 'белого листа'. Он работает полностью автономно от контент-календаря "
            "и не ломает конверсионную цепочку продаж. Пользователь в 1 клик выбирает готовую рубрику: "
            "'Новинка в каталоге', 'Акция или скидка', 'Анонс события', 'История бренда', 'Атмосфера', 'Отзыв гостя'. "
            "Также система анализирует дату, праздники и инфоповоды города/страны, предлагая актуальные темы в поле ввода (динамические плейсхолдеры)."
        )
    },
    {
        "id": "ucust_clean_rag",
        "source": "technology",
        "title": "Clean RAG и защита от галлюцинаций",
        "content": (
            "В UCust AI интегрирован Clean RAG — движок локального семантического поиска по базе знаний бренда. "
            "Перед генерацией текста система подтягивает проверенные факты (меню, цены, адреса, правила доставки, сертификаты). "
            "Агент-критик Чарли Мангера сверяет черновик с базой фактов (FactSheet) и блокирует галлюцинации нейросети. "
            "Пользователь получает 100% достоверный контент без выдуманных условий и ложных обещаний."
        )
    },
    {
        "id": "ucust_photo_realism",
        "source": "technology",
        "title": "Фотореалистичный визуал на GPU RTX 3090",
        "content": (
            "Генерация графики происходит через локальный кластер ComfyUI на модели Qwen-Image 2512 с технологией LoRA RealSkinFix. "
            "В отличие от стандартных нейросетей, визуал UCust лишен эффекта 'пластиковой кожи', искажения пальцев и замыленности. "
            "Система учитывает эстетику бизнеса (лофт, крафт, минимализм, сканди) и физику кадра (пар от свежего кофе, текстура выпечки, блеск металла)."
        )
    },
    {
        "id": "ucust_funnel_architecture",
        "source": "marketing",
        "title": "Конверсионная воронка контента (TOFU -> MOFU -> BOFU)",
        "content": (
            "UCust строит контент-стратегию не хаотично, а по законам маркетинга: "
            "1. TOFU (Top of Funnel): вовлекающие посты, разбор мифов, юмор и праздники для знакомства с новой аудиторией. "
            "2. MOFU (Middle of Funnel): экспертные обзоры, сравнения, закулисье и разбор болей для формирования доверия. "
            "3. BOFU (Bottom of Funnel): горячие офферы, акции, промокоды и отзывы гостей для закрытия сделки. "
            "Советник воронки (Funnel Integrity Advisor) гарантирует баланс пользы и продаж в ленте."
        )
    },
    {
        "id": "ucust_onboarding_speed",
        "source": "onboarding",
        "title": "Экспресс-онбординг за 60 секунд",
        "content": (
            "Чтобы настроить команду ИИ под свой бизнес, владельцу достаточно указать сайт, соцсети или загрузить прайс/меню. "
            "Универсальный коллектор парсит информацию, формирует ДНК бренда (Brand DNA), фиксирует Tone of Voice и целевую аудиторию. "
            "Уже через минуту система готова выдать первый контент-план и сгенерировать посты с визуалом."
        )
    },
    {
        "id": "ucust_tariffs_and_value",
        "source": "commercial",
        "title": "Тарифы и бизнес-эффект",
        "content": (
            "Бизнес-эффект от внедрения UCust AI: "
            "— Экономия до 85% бюджета на SMM-агентствах и копирайтерах. "
            "— Время на согласование публикаций снижается с 15 часов до 10 минут в неделю. "
            "— Доступны форматы: одиночные посты, карусели из 3-5 ракурсов, опросы аудитории, викторины со спойлерами и интерактивные пазлы. "
            "Тарифы: START (для небольших проектов), BUSINESS (полная команда агентов и LoRA фото), ENTERPRISE (изолированный GPU-контур)."
        )
    }
]

def seed_ucust_knowledge():
    print("=" * 75)
    print("🚀 ИНИЦИАЛИЗАЦИЯ БАЗЫ ЗНАНИЙ И ПРОФИЛЯ ДЛЯ UCUST AI")
    print("=" * 75)

    # 1. Поиск рабочего подключения
    from scripts.inspect_rag_and_users import find_working_engine
    engine, label, url = find_working_engine()
    print(f"Используется база данных: {label}\n")

    # 2. Создание таблиц (если еще не созданы)
    with engine.connect() as conn:
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            conn.commit()
        except Exception:
            pass

    StorageBase.metadata.create_all(bind=engine)
    try:
        inspector = inspect(engine)
        if "user_profiles" in inspector.get_table_names():
            cols = {c["name"] for c in inspector.get_columns("user_profiles")}
            with engine.connect() as conn:
                if "company_name" not in cols:
                    conn.execute(text("ALTER TABLE user_profiles ADD COLUMN company_name VARCHAR(256)"))
                if "social_links" not in cols:
                    conn.execute(text("ALTER TABLE user_profiles ADD COLUMN social_links JSON"))
                if "visual_grid_dna" not in cols:
                    conn.execute(text("ALTER TABLE user_profiles ADD COLUMN visual_grid_dna JSON"))
                if "brand_dossier" not in cols:
                    conn.execute(text("ALTER TABLE user_profiles ADD COLUMN brand_dossier JSON"))
                if "connected_channels" not in cols:
                    conn.execute(text("ALTER TABLE user_profiles ADD COLUMN connected_channels JSON DEFAULT '[]'"))
                conn.commit()
    except Exception:
        pass

    try:
        RAGBase.metadata.create_all(bind=engine)
    except Exception:
        # Fallback на JSON-таблицы
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS tenant_knowledge_chunks (
                    chunk_id VARCHAR PRIMARY KEY,
                    tenant_id VARCHAR NOT NULL,
                    source_type VARCHAR NOT NULL,
                    content TEXT NOT NULL,
                    embedding JSON NOT NULL
                );
                CREATE TABLE IF NOT EXISTS brand_profiles (
                    tenant_id VARCHAR PRIMARY KEY,
                    company_name VARCHAR NOT NULL,
                    industry_type VARCHAR NOT NULL,
                    tone_of_voice TEXT,
                    brand_props JSON,
                    contacts JSON,
                    forbidden_topics JSON
                );
            """))
            conn.commit()

    SessionMaker = sessionmaker(bind=engine)
    session = SessionMaker()

    # 3. Сохранение профиля в user_profiles
    profile = session.query(UserProfile).filter(
        (UserProfile.user_id == TENANT_ID) | (UserProfile.external_user_id == TENANT_ID)
    ).first()

    profile_data = {
        "user_id": TENANT_ID,
        "external_user_id": TENANT_ID,
        "company_name": COMPANY_NAME,
        "niche": "IT, B2B SaaS, Автономный SMM & ИИ-маркетинг",
        "city": "Москва",
        "country": "Россия",
        "target_audience": "Предприниматели, владельцы малого и среднего бизнеса (кафе, ритейл, бьюти), маркетологи и digital-агентства",
        "step1": {
            "voice_and_tone": "Экспертный, технологичный, энергичный, вдохновляющий, без клише и воды",
            "positioning": "Первая полностью автономная команда ИИ-агентов для маркетинга бизнеса",
            "brand_colors": ["#0F172A", "#6366F1", "#10B981"]
        },
        "step2": {
            "geography": "Россия и СНГ, онлайн",
            "usp": "Контент-команда полного цикла на автопилоте: от онбординга за 60 секунд до публикации в Telegram и VK с фотореалистичной графикой"
        },
        "step3": {
            "strengths": [
                "Мультиагентная архитектура (Оркестратор + Копирайтер + Критик + Фотограф)",
                "Фотогенерация уровня ComfyUI Qwen-Image 2512 без пластика",
                "Clean RAG защита от галлюцинаций",
                "Нативное богатое форматирование Telegram 7.2+ (спойлеры, цитаты, промокоды)"
            ]
        },
        "step4": {
            "services": [
                "Генерация коммерческих постов под ключ",
                "Автономный контент-план и календарь публикаций",
                "Интеллектуальный Банк Идей с защитой воронки продаж",
                "Интерактивные форматы: опросы, викторины, карусели"
            ]
        },
        "step5": {
            "goals": [
                "Привлечение предпринимателей на платформу UCust",
                "Демонстрация возможностей автономного ИИ в реальном бизнесе",
                "Освобождение времени предпринимателей от рутины создания контента"
            ]
        },
        "connected_channels": ["telegram", "vk", "max_messenger"]
    }

    if not profile:
        profile = UserProfile(**profile_data)
        session.add(profile)
        session.commit()
        print(f"✅ Профиль '{COMPANY_NAME}' успешно создан в user_profiles (ID: {profile.id})")
    else:
        for k, v in profile_data.items():
            setattr(profile, k, v)
        session.commit()
        print(f"✅ Профиль '{COMPANY_NAME}' успешно обновлен в user_profiles (ID: {profile.id})")

    session.close()

    # 4. Сохранение чанков в tenant_knowledge_chunks
    with engine.connect() as conn:
        for doc in UCUST_KNOWLEDGE_DOCS:
            conn.execute(
                text("""
                    INSERT INTO tenant_knowledge_chunks (chunk_id, tenant_id, source_type, content, embedding)
                    VALUES (:cid, :tid, :src, :content, :emb)
                    ON CONFLICT (chunk_id) DO UPDATE SET 
                        content = EXCLUDED.content,
                        source_type = EXCLUDED.source_type;
                """),
                {
                    "cid": f"ucust_{doc['id']}",
                    "tid": TENANT_ID,
                    "src": doc["source"],
                    "content": f"{doc['title']}: {doc['content']}",
                    "emb": "[]"
                }
            )
        conn.commit()
    print(f"✅ Успешно загружено {len(UCUST_KNOWLEDGE_DOCS)} чанков знаний в RAG (Таблица: tenant_knowledge_chunks)")

    # 5. Проверка семантического поиска
    try:
        from rag.pipeline import CleanRAGPipeline
        from rag.models import Document
        rag = CleanRAGPipeline()
        rag_docs = [
            Document(doc_id=d["id"], text=d["content"], source=d["source"], metadata={"title": d["title"]})
            for d in UCUST_KNOWLEDGE_DOCS
        ]
        rag.ingest_documents(rag_docs)
        print("✅ База знаний успешно проиндексирована в CleanRAGPipeline (In-Memory)")

        # Тест запроса
        test_q = "Как UCust защищает от галлюцинаций и какие форматы поддерживает?"
        res = rag.query(test_q)
        print(f"\n🔍 Тест поиска: '{test_q}'")
        print(f"   Результат: найдено {len(res.chunks)} чанков (Confidence: {round(res.top_score, 2)})")
        if res.chunks:
            print(f"   Топ чанк: {res.chunks[0].text[:120]}...\n")
    except Exception as e:
        print(f"ℹ️ Уведомление по CleanRAGPipeline: {e}")

    print("=" * 75)
    print("🎉 БАЗА ЗНАНИЙ ДЛЯ UCUST AI УСПЕШНО ГОТОВА!")
    print("=" * 75)
    print("\n💡 Теперь можно сгенерировать первый пост про саму систему, выполнив:")
    print("   python scripts/run_autonomous_campaign.py \\")
    print("     --company \"UCust AI\" \\")
    print("     --niche \"автономный SMM & ИИ-маркетинг\" \\")
    print("     --prompt \"Как команда автономных ИИ-агентов освобождает предпринимателю 15 часов в неделю\" \\")
    print("     --tone \"Экспертный, вдохновляющий, технологичный\" \\")
    print("     --format single \\")
    print("     --spoiler \"Первые 30 постов можно сгенерировать бесплатно!\" \\")
    print("     --promo \"AUTOPILOT2026\" \\")
    print("     --channel \"@testaipublisher\"\n")

if __name__ == "__main__":
    seed_ucust_knowledge()

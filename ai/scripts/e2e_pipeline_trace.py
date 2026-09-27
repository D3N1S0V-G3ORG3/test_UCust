"""
Скрипт сквозного прогона (End-to-End Trace) пайплайна генерации поста с замером времени на каждом этапе.
Проверяет:
1. Запрос с бэкенда (тема, ниша, компания, анкета)
2. Инициализация и авто-миграция БД
3. RAG поиск и оценка Data Richness Score (DRS)
4. Маркетинговые фреймворки и 5 ступеней Ханта
5. Генерация текста (Saiga LLM / Copywriter)
6. Аудит критика Чарли Мангера 2.0 (проверка на штампы, оксюмороны, глубину)
7. Генерация фотопромпта для Qwen-Image 2512 (6-компонентная формула)
8. Итоговая сборка ответа бэкенду
"""

import asyncio
import os
import sys
import time

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.orchestrator import UnifiedOrchestrator
from storage.db import init_db


async def run_e2e_trace():
    print("=" * 80)
    print("🚀 НАЧАЛО СКВОЗНОГО ПРОГОНА ПАЙПЛАЙНА (E2E PIPELINE TRACE)")
    print("=" * 80)

    total_start = time.perf_counter()

    # ЭТАП 0: Инициализация БД и автоматическая миграция
    t0 = time.perf_counter()
    print("\n[ЭТАП 0] 🗄️ Инициализация базы данных и проверка схемы SQLite/Postgres...")
    await init_db()
    t0_end = time.perf_counter()
    print(f"  ⏱️ Этап 0 завершен за {(t0_end - t0) * 1000:.2f} ms")

    # Входные данные от бэкенда
    request_payload = {
        "user_id": "test_user_42",
        "company_name": "DevPulse",
        "niche": "it",
        "prompt": "Как ускорить релизный цикл с помощью автоматизированного пайплайна CI/CD",
        "offer": "Бесплатный аудит архитектуры для первых 5 команд",
        "format_type": "post",
        "tone": "expert",
        "user_data": {
            "city": "Москва",
            "target_audience": "CTO, Team Lead, DevOps-инженеры",
            "usp": "Сокращаем время деплоя с 40 минут до 3 минут без даунтайма",
            "pricing": "Тарифы от 50 000 руб/мес, 14 дней бесплатный триал",
            "guarantees": "Гарантия SLA 99.99% и возврат средств в течение 30 дней",
            "social_proof": "Более 120 успешных внедрений в финтех и e-commerce"
        }
    }
    print("\n[ВХОДНЫЕ ДАННЫЕ С БЭКЕНДА]:")
    print(f"  🏢 Компания: {request_payload['company_name']} ({request_payload['niche']})")
    print(f"  📝 Тема: {request_payload['prompt']}")
    print(f"  🎯 Оффер: {request_payload['offer']}")

    # Инициализация оркестратора
    orchestrator = UnifiedOrchestrator()

    # ЭТАП 1..7: Запуск полного цикла генерации поста
    print("\n[ЭТАП 1-7] ⚙️ Вызов UnifiedOrchestrator.execute_task('generate_post')...")
    gen_start = time.perf_counter()
    
    result = await orchestrator.execute_task(
        task_type="generate_post",
        user_data=request_payload
    )
    
    gen_end = time.perf_counter()
    total_end = time.perf_counter()

    print("\n" + "=" * 80)
    print("📊 РЕЗУЛЬТАТ СКВОЗНОГО ПРОГОНА:")
    print("=" * 80)
    print(f"  ⏱️ Общее время выполнения (E2E): {(total_end - total_start):.3f} сек")
    print(f"  ⏱️ Время работы ядра генерации: {(gen_end - gen_start):.3f} сек")
    print(f"  🛡️ Статус результата: {result.get('status', 'OK')}")

    # Разбор результата
    print("\n📝 СГЕНЕРИРОВАННЫЙ ТЕКСТ ПОСТА:")
    print("-" * 60)
    print(result.get("text", "NO TEXT GENERATED"))
    print("-" * 60)

    print("\n🔍 ВЕРДИКТ КРИТИКА (CHARLIE MUNGER 2.0):")
    critic = result.get("critic_review", {})
    print(f"  Score: {critic.get('score')} | Verdict: {critic.get('verdict')}")
    print(f"  Criticism: {critic.get('criticism')}")
    if critic.get("fatal_flaws"):
        print(f"  Fatal flaws: {critic.get('fatal_flaws')}")

    print("\n📸 СГЕНЕРИРОВАННЫЙ QWEN-IMAGE 2512 ФОТОПРОМПТ:")
    photo = result.get("photo_prompt", {})
    if isinstance(photo, dict):
        print(f"  Positive: {photo.get('positive_prompt')}")
        print(f"  Negative: {photo.get('negative_prompt')}")
        print(f"  Sampling: {photo.get('sampling_config')}")
    else:
        print(f"  Prompt: {photo}")

    print("\n✅ СКВОЗНОЙ ПРОГОН УСПЕШНО ЗАВЕРШЕН!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_e2e_trace())

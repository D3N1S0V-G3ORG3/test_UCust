# Отчет по связям и интеграциям «UCust.AI»

Дата: 2026-02-10

## 1. Общая схема взаимодействий

- API слой (`bridge/api_controller.py`) принимает запросы от внешнего Java‑сайта и запускает цепочку агентов в фоне.
- Оркестратор (`core/orchestrator.py`) запускает агентов по очереди и собирает технический лог.
- Агенты (`core/agents.py`) используют:
  - SQL‑хранилище (PostgreSQL через SQLAlchemy) для анкеты пользователя и задач.
  - Модули парсинга (заглушки Telethon/VK).
  - Лингвистический фильтр (заглушка RoSBERTa).
  - Нейросетевой генеративный модуль (заглушка Saiga).
  - Векторное хранилище эмбеддингов (заглушка ChromaDB/FAISS) для контроля дублей.
- Java‑bridge (`bridge/java_bridge.py`) предоставляет контракты для интеграции с внешним Java‑backend.

## 2. API слой (FastAPI)

Файл: `bridge/api_controller.py`

### POST /api/v1/process (дублируется как /process)

- Вход: `user_id`
- Действия:
  1. Загружает анкету пользователя из SQL через `storage/repository.py:get_user_questionnaire`.
  2. Если анкета не найдена → 404.
  3. Создает задачу в SQL через `storage/repository.py:create_content_task` со статусом `PENDING`.
  4. Запускает фоновую задачу `BackgroundTasks`.
- Выход: `job_id`, статус `accepted`.

### GET /api/v1/status/{job_id}

- Вход: `job_id`
- Действия:
  1. Получает запись задачи через `storage/repository.py:get_task_status`.
  2. Если задача не найдена → 404.
  3. Возвращает статус `PENDING/PROCESSING/COMPLETED/FAILED`.
  4. При `COMPLETED` возвращает результат (`post_text` или `image_link` из `result_payload`).
  5. При `FAILED` возвращает краткое `error`.

## 3. Оркестратор и агенты

Файлы: `core/orchestrator.py`, `core/agents.py`

- `build_default_orchestrator()` собирает цепочку:
  1. `Agent_Interviewer`
  2. `Agent_Analyst`
  3. `Agent_Copywriter`
  4. `Agent_Visual_Director`

### Agent_Interviewer
- Валидирует анкету и сохраняет в SQL (`UserProfile`).

### Agent_Analyst
- Забирает данные из `TelethonCollector` и `VkApiCollector`.
- Пропускает текст через `PreProcessor`.
- Формирует SWOT и стратегию через `GenerativeCore`.

### Agent_Copywriter
- Генерирует черновик поста и проверяет дубли через `InMemoryVectorStore`.
- Поддерживает `inject_custom_event(event_type, context, source_text)` для ручного вброса событий:
  - `gratitude`
  - `achievement`
  - `emergency`
  - `custom_edit`

### Agent_Visual_Director
- Формирует сетку контента и промпты для Kandinsky.

### Notification + User Intercept
- Новый модуль: `core/notifier.py`.
- `AgentOrchestrator` после генерации контента отправляет callback через `NotificationGateway`.
- При ответе `AWAITING_USER_ACTION` оркестратор переводит задачу в точку перехвата:
  - состояние `Ожидание решения пользователя`
  - статус задачи в SQL: `AWAITING_USER_ACTION`
- После `APPROVED` задача переводится в `COMPLETED`.

## 4. SQL‑хранилище (PostgreSQL)

Файлы: `storage/db.py`, `storage/models.py`, `storage/repository.py`

### Таблицы
- `user_profiles` — анкета пользователя (шаги 1–5).
- `project_metadata` — метаданные проекта.
- `publication_history` — история публикаций.
- `content_tasks` — задачи генерации контента (статусы и ошибки).

### Репозиторий
- `get_user_questionnaire()` — загрузка анкеты по `user_id`.
- `create_content_task()` — создание задачи.
- `update_content_task_status()` — обновление статуса + error/result.
- `get_task_status()` — получение статуса задачи.

## 5. Векторное хранилище эмбеддингов

Файл: `storage/vector_store.py`

- Интерфейс `VectorStore` и реализация `InMemoryVectorStore`.
- Используется `Agent_Copywriter` для проверки уникальности контента.

## 6. Логирование

Файл: `bridge/api_controller.py`

- Стандартный `logging` пишет в `app_log.log`.
- Логи включают:
  - Запуск агентов
  - Технические логи цепочки
  - Traceback при критических ошибках

## 7. Интеграция с Java‑backend

Файл: `bridge/java_bridge.py`

- Заглушки отправки анкеты, черновика поста и промпта Kandinsky.
- Контракты соответствуют Pydantic‑моделям из `schemas/models.py`.

## 8. Ключевые контракты

Файл: `schemas/models.py`

- Анкета пользователя (5 шагов)
- Метаданные проекта
- История публикаций
- SWOT и стратегия
- Черновик поста
- План сетки и промпты для Kandinsky

---

## 9. Mermaid-диаграммы

### 9.1. ER‑диаграмма SQL‑схемы

```mermaid
erDiagram
    USER_PROFILES ||--o{ PROJECT_METADATA : has
    PROJECT_METADATA ||--o{ PUBLICATION_HISTORY : has
    USER_PROFILES ||--o{ CONTENT_TASKS : has

    USER_PROFILES {
        int id PK
        string external_user_id
        json step1
        json step2
        json step3
        json step4
        json step5
        datetime created_at
    }

    PROJECT_METADATA {
        int id PK
        int user_profile_id FK
        string name
        string niche
        json platforms
        datetime created_at
    }

    PUBLICATION_HISTORY {
        int id PK
        int project_id FK
        string platform
        text post_text
        string status
        json metadata
        datetime published_at
    }

    CONTENT_TASKS {
        int id PK
        int user_profile_id FK
        string status
        text error_message
        json result_payload
        datetime created_at
        datetime updated_at
    }
```

### 9.2. Последовательность запуска обработки (POST /api/v1/process)

```mermaid
sequenceDiagram
    autonumber
    participant Client as Java‑site
    participant API as FastAPI
    participant Repo as Storage Repository
    participant SQL as PostgreSQL
    participant Orchestrator as AgentOrchestrator
    participant Agents as Agents Chain

    Client->>API: POST /api/v1/process {user_id}
    API->>Repo: get_user_questionnaire(user_id)
    Repo->>SQL: SELECT user_profiles
    SQL-->>Repo: questionnaire
    Repo-->>API: questionnaire
    API->>Repo: create_content_task(PENDING)
    Repo->>SQL: INSERT content_tasks
    SQL-->>Repo: job_id
    Repo-->>API: job_id
    API-->>Client: 202 Accepted + job_id

    par Background task
        API->>Repo: update_content_task_status(PROCESSING)
        Repo->>SQL: UPDATE content_tasks
        API->>Orchestrator: run(context)
        Orchestrator->>Agents: Agent_Interviewer → Agent_Analyst → Agent_Copywriter → Agent_Visual_Director
        Agents-->>Orchestrator: context + logs
        Orchestrator-->>API: context
        API->>Repo: update_content_task_status(COMPLETED, result_payload)
        Repo->>SQL: UPDATE content_tasks
    end
```

### 9.3. Проверка статуса (GET /api/v1/status/{job_id})

```mermaid
sequenceDiagram
    autonumber
    participant Client as Java‑site
    participant API as FastAPI
    participant Repo as Storage Repository
    participant SQL as PostgreSQL

    Client->>API: GET /api/v1/status/{job_id}
    API->>Repo: get_task_status(job_id)
    Repo->>SQL: SELECT content_tasks
    SQL-->>Repo: task
    Repo-->>API: task
    API-->>Client: status + result/error
```

### 9.4. User Intercept + Event Injection

```mermaid
sequenceDiagram
    autonumber
    participant Client as Java-site
    participant API as FastAPI
    participant SQL as PostgreSQL
    participant Orch as AgentOrchestrator
    participant Notify as NotificationGateway
    participant Copy as Agent_Copywriter

    API->>Orch: run(context)
    Orch->>Notify: notify_user_for_approval(post)
    Notify-->>Orch: AWAITING_USER_ACTION
    Orch-->>API: context.pending_user_action = true
    API->>SQL: UPDATE content_tasks.status = AWAITING_USER_ACTION

    Client->>API: POST /api/v1/action/{job_id} {action,event_type,context}
    alt action = APPROVED
        API->>SQL: UPDATE status = COMPLETED
    else action = EDIT/REGENERATE
        API->>Copy: inject_custom_event(...)
        Copy-->>API: updated post text
        API->>SQL: UPDATE payload + keep AWAITING_USER_ACTION
    end
```

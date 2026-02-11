**Инструкция по тестированию**

Этот файл описывает ручные проверки для ключевых блоков системы.

**Предусловия**
- Активная виртуальная среда Python.
- Установлены зависимости FastAPI и SQLAlchemy.

**Проверка логики агентов**
1. Подготовить тестовую анкету `UserQuestionnaire`.
2. Запустить `build_default_orchestrator()` и выполнить `run(context)`.
3. Убедиться, что в логе есть переходы состояний:
   - `Ожидание -> Данные собраны`
   - `Данные собраны -> Анализ завершен`
   - `Анализ завершен -> Контент сформирован`
   - `Контент сформирован -> Ожидание решения пользователя` (в режиме перехвата)

**Проверка Notification + User Intercept**
1. Запустить `POST /api/v1/process`.
2. Дождаться статуса задачи `AWAITING_USER_ACTION`.
3. Проверить, что `GET /api/v1/status/{job_id}` возвращает `action_required=true`.
4. Выполнить `POST /api/v1/action/{job_id}` с `action=APPROVED` и убедиться, что статус стал `COMPLETED`.

**Проверка Event Injection**
1. Для задачи в `AWAITING_USER_ACTION` отправить `POST /api/v1/action/{job_id}` с:
   - `action=EDIT`, `event_type=custom_edit`, `context=<правки пользователя>`
   - или `action=REGENERATE`, `event_type=gratitude`, `context=<праздничный повод>`
2. Проверить, что задача осталась в `AWAITING_USER_ACTION`, а `result` обновился.

**Проверка rule-based SWOT**
1. Создать анкету с B2B (`step2` содержит `b2b`).
2. Убедиться, что в `context.swot.strengths` есть экспертные формулировки.
3. Изменить анкету на B2C и проверить, что вывод меняется.
4. Установить 5+ конкурентов в `step5.competitors` и проверить появление угрозы высокой конкуренции.

**Проверка semantic_filter**
1. Создать `InMemoryVectorStore` и добавить запись с `metadata={"niche": "кухни", "city": "Москва"}`.
2. Запустить `semantic_filter` с теми же метаданными и убедиться, что `uniqueness_score < 1.0`.
3. Запустить `semantic_filter` с другой нишей/городом и убедиться, что `uniqueness_score == 1.0`.

**Проверка HybridStorageManager**
1. Создать `HybridStorageManager()`.
2. Вызвать `save_questionnaire` и убедиться, что возвращается `id`.
3. Вызвать `evaluate_and_store_post` с текстом и метаданными и убедиться, что возвращается `uniqueness_score`.

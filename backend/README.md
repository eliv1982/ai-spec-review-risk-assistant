# Backend

Бэкенд для проекта **AI Specification Review & Risk Assistant** — сервиса для проверки
технических спецификаций, требований к проекту, feature request'ов, автоматизационных
брифов и бизнес-требований. Подробности о продукте см. в `../PROJECT_SCOPE.md` и `../docs/`.

## Текущий этап

Реализован фундамент бэкенда (слой персистентности и все эндпоинты создания/чтения/
списка, не связанные с ИИ), строгая схема проверки вместе с детерминированным контролем
качества (QC), а также — на этом этапе — клиент OpenAI Structured Outputs. А именно:

- приложение FastAPI со стартапом (`lifespan`) и созданием схемы базы данных;
- модели SQLAlchemy для таблиц `documents`, `reviews`, `audit_runs`;
- атомарное создание документа вместе с записью аудита (`document.create`);
- эндпоинты чтения и списка для документов, проверок (`reviews`) и записей аудита, с
  фильтрацией, пагинацией и детерминированной сортировкой;
- конфигурация через переменные окружения;
- CORS, ограниченный списком настроенных origin'ов;
- строгие Pydantic-схемы `ModelReviewDraft` и `FinalReview` (и вложенные `Risk`,
  `MissingRequirement`, `Contradiction`) с запретом лишних полей, закрытыми
  перечислениями и строгой валидацией строк и булевых значений;
- детерминированный сервис контроля качества, который по проверенному
  `ModelReviewDraft` строит `FinalReview`: флаг `needs_review` и коды причин
  `review_reason_codes` формирует исключительно бэкенд — модель не предлагает и не
  сохраняет ни одного кода причины;
- безопасная фабрика отката (fallback) для типовых технических сбоев (`MODEL_ERROR`,
  `INVALID_JSON`, `SCHEMA_MISMATCH`) — без выдуманных находок, с русскоязычным резюме
  и одним безопасным уточняющим вопросом;
- клиент OpenAI Structured Outputs (`app/llm/`): синхронный, нестриминговый вызов
  `client.responses.with_raw_response.parse(...)` с `text_format=ModelReviewDraft` и
  `store=False`. Сначала проверяется top-level `status` сырого ответа; только для
  `status="completed"` вызывается `raw_response.parse()`, запускающий разбор Structured
  Outputs, и результат берётся из `response.output_parsed`. Это гарантирует, что
  ответ со `status="incomplete"` (частичный/усечённый `output_text`) классифицируется
  как `LLMProviderError`, а не ошибочно как invalid JSON или schema mismatch. Успех
  возвращается как валидированный экземпляр `ModelReviewDraft`, либо выбрасывается одна
  из типизированных ошибок (`LLMConfigurationError`, `LLMProviderError`, `LLMAPIError`,
  `LLMTransportError`, `LLMInvalidJSONError`, `LLMSchemaMismatchError`);
- системный prompt на русском языке (`app/llm/prompts.py`), требующий рецензировать
  только переданный документ, отвечать на русском, относиться к тексту документа как к
  недоверенным данным, игнорировать встроенные в документ инструкции, не выдумывать
  находки и никогда не возвращать `needs_review`/`review_reason_codes` или иные поля
  вне схемы `ModelReviewDraft`; закреплены версии:
  `PROMPT_VERSION = "spec-review-prompt-v1"`, `REVIEW_SCHEMA_VERSION = "spec-review-schema-v1"`;
- автоматические тесты на изолированной временной базе SQLite, включая обширные тесты
  строгих схем, детерминированного QC, фабрики отката, prompt-констант и LLM-клиента.
  Тесты клиента полностью офлайн: большинство используют инжектируемый fake/stub-клиент
  (или ошибки SDK, поднятые напрямую в тесте), а отдельные regression-тесты используют
  настоящий `openai==2.53.0` с HTTP-ответами, подменёнными через `httpx.MockTransport`.
  Ни один тест не обращается к внешней сети или реальному OpenAI API и не требует
  переменной окружения `OPENAI_API_KEY`;
- слой review orchestration (`app/services/review_orchestrator.py`, класс
  `ReviewOrchestrator` с внедряемым через конструктор LLM-клиентом): связывает уже
  готовые компоненты в единый пайплайн `document_text → LLM-клиент → ModelReviewDraft →
  детерминированный QC → FinalReview`. Happy path — успешный вызов LLM-клиента, затем
  `build_final_review`. Fallback path перехватывает только типизированный
  `LLMClientError`, классифицирует его в закрытый enum `LLMErrorCategory`
  (`app/enums.py`) и строит `FinalReview` через уже существующую безопасную фабрику
  отката `build_fallback_review` — без второго вызова LLM, без ручной сборки
  `FinalReview` и без изменения детерминированных правил QC/fallback. Любое иное
  исключение (программная ошибка, сбой внутри QC или фабрики отката,
  `KeyboardInterrupt`, `SystemExit`) не перехватывается и распространяется наружу как
  есть. Результат — строгая Pydantic-модель `ReviewOrchestrationResult`
  (`final_review`, `used_fallback`, `llm_error_category`) для будущего
  persistence/audit-слоя; она не содержит исходное исключение, текст ошибки, ответ
  провайдера, секреты или полный текст документа, а `llm_error_category` никогда не
  попадает в `FinalReview.review_reason_codes`. Тесты (`tests/test_review_orchestrator.py`)
  полностью офлайн и используют только инжектируемый fake-клиент.
- workflow сохранения проверки и аудита (`app/services/review_workflow.py`, класс
  `ReviewWorkflow` с внедряемыми через конструктор `Session` и orchestrator'ом по
  минимальному `Protocol`): для существующего документа один раз вызывает orchestrator,
  затем атомарно сохраняет `Review` и `AuditRun` в одной транзакции. Граница транзакций
  соблюдается строго: после чтения документа его id/text копируются в локальные
  Python-значения, read-only autobegin-транзакция закрывается (`session.rollback()`), и
  только после этого вызывается orchestrator — во время вызова `session.in_transaction()
  is False`. Короткая write-транзакция открывается только для повторной проверки
  документа (на случай удаления между чтением и записью — тогда бросается
  `DocumentNotFoundError` без audit-записи, это не сбой попытки проверки, а её
  отсутствие) и записи `Review` + `AuditRun`; все значения для результата читаются после
  `flush()`, но до `commit()`, поэтому post-commit `refresh()` не нужен и после любого
  пути возврата `session.in_transaction() is False`. Перед любой записью в БД результат
  orchestrator'а проверяется на внутреннюю согласованность: `used_fallback=True` без
  `final_review.needs_review=True` отклоняется как `InvalidReviewWorkflowResultError` до
  создания `Review`/`AuditRun` — стандартный `ReviewOrchestrator` такого не производит, но
  ничего не мешает нестандартной injected-реализации. Аудит-`status` определяется
  исключительно по итоговому `FinalReview.needs_review` (`False → success`,
  `True → needs_review`); безопасный LLM-fallback, давший пригодный к сохранению
  `FinalReview`, тоже сохраняется как `needs_review` с `error=null` — это не техническая
  ошибка аудита. `prompt_version`/`review_schema_version` (константы из
  `app/llm/prompts.py`) и метаданные `used_fallback`/`llm_error_category` попадают в
  `input_json`/`output_json` записи аудита, а не в `FinalReview`. Любая непредвиденная
  ошибка (не безопасный LLM-fallback и не отсутствующий документ, а сбой в
  orchestrator/QC/персистентности или невалидный orchestration result) откатывает
  незавершённую транзакцию, пишет отдельную `AuditRun(status="error")` с фиксированным
  нечувствительным сообщением (без `str(exc)`, трассировки, текста документа или ответа
  провайдера) на сущности `document`, а затем исходное исключение пробрасывается наружу
  без изменений; `KeyboardInterrupt`/`SystemExit`/`GeneratorExit` никогда не перехватываются.
  Результат — неизменяемая (`frozen`) Pydantic-модель `PersistedReviewResult` с расширенным
  набором инвариантов (`used_fallback`/`audit_status`/`final_review.needs_review` должны
  быть согласованы), а вложенный `final_review` — это `PersistedFinalReviewSnapshot`
  (frozen-подкласс `FinalReview`, локальный для этого модуля), так что
  `result.final_review.needs_review = ...` отклоняется как обычная mutation
  frozen-Pydantic-модели, а не только переприсваивание самого поля `final_review`.
  `Document.status` этот слой не меняет — такой переход этим этапом не утверждён.
  Тесты (`tests/test_review_workflow.py`) полностью офлайн, используют инжектируемый
  fake-orchestrator и изолированную временную базу SQLite, включая проверки границы
  транзакций, невалидного fallback-результата, неизменяемости snapshot'а, состояния
  session после закрытия и после сбоя error-audit, повторных запусков и
  `KeyboardInterrupt`/`SystemExit`.

Схема проверки, QC, клиент OpenAI, слой orchestration и workflow сохранения на этом
этапе — это внутренний, полностью протестированный слой, не подключённый ни к одному
эндпоинту: запустить настоящую ИИ-проверку через API пока нельзя.

**Ещё не реализовано на этом этапе** (сознательно вне рамок текущего этапа):

- эндпоинты запуска ИИ-проверки — `POST /api/documents/{document_id}/review` и
  `POST /api/ai/review`;
- audit для эндпоинта `POST /api/ai/review` (`ai.review`);
- изменение `Document.status` по итогам проверки (например, переход в `reviewed`/
  `review_failed`) — вне рамок текущего этапа;
- экспорт проверки в JSON (`GET /api/reviews/{review_id}/export`);
- фронтенд;
- Docker.

## Структура проекта

```
backend/
  app/
    main.py           приложение FastAPI, lifespan (init_db), CORS, обработчик 500-й ошибки
    config.py         настройки (pydantic-settings): переменные окружения + .env
    database.py       engine/session, PRAGMA foreign_keys=ON, init_db, get_db
    enums.py          DocumentStatus, ReviewConfidence, ReviewReadiness, AuditStatus,
                      RiskSeverity, RiskCategory, ReviewReasonCode, LLMErrorCategory
    models.py         модели SQLAlchemy: Document, Review, AuditRun
    api/              роутеры: health, documents, reviews, audit_runs
    schemas/          Pydantic-схемы запросов/ответов, обёртка пагинации, строгие
                      ModelReviewDraft / FinalReview и вложенные схемы (review.py)
    repositories/     операции персистентности для каждой таблицы
    services/         document_service (атомарное создание + аудит), audit_service
                      (инвариант), review_qc (детерминированный QC и фабрика отката),
                      review_orchestrator (ReviewOrchestrator: LLM-клиент → QC →
                      FinalReview, с fallback-путём при LLMClientError),
                      review_workflow (ReviewWorkflow: атомарное сохранение Review +
                      AuditRun для существующего документа, PersistedReviewResult)
    llm/              клиент OpenAI Structured Outputs: client.py (OpenAIReviewClient,
                      метод review(document_text) -> ModelReviewDraft), errors.py
                      (типизированные ошибки LLMConfigurationError/LLMProviderError/
                      LLMAPIError/LLMTransportError/LLMInvalidJSONError/
                      LLMSchemaMismatchError), prompts.py (системный prompt на русском,
                      PROMPT_VERSION, REVIEW_SCHEMA_VERSION)
    utils/            utc_now_iso(), JSONText (сериализация JSON-колонок), нормализация
                      текста и правило "слишком расплывчато" (text.py)
  tests/              conftest.py, helpers.py и тестовые модули
  requirements.txt, pytest.ini, README.md
```

## Требования

- Python 3.11 или новее.

## Установка окружения

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
```

Скопируйте `.env.example` из корня репозитория в `.env` (тоже в корне репозитория, рядом
с `.env.example`) и при необходимости заполните значения:

```bash
cp ../.env.example ../.env
```

`OPENAI_API_KEY` не требуется для запуска приложения и не требуется для тестов: ни один
эндпоинт пока не вызывает клиент OpenAI, а тесты `app/llm/` либо используют
инжектируемый fake-клиент, либо настоящий SDK с HTTP-ответами, подменёнными через
`httpx.MockTransport` — в обоих случаях без обращения к реальному OpenAI API.

### Переменные окружения (`.env.example`)

| Переменная | Назначение |
| --- | --- |
| `OPENAI_API_KEY` | ключ OpenAI; читается `OpenAIReviewClient`, но пока не вызывается ни одним эндпоинтом |
| `OPENAI_MODEL` | название модели OpenAI; читается `OpenAIReviewClient`, но пока не вызывается ни одним эндпоинтом |
| `DATABASE_URL` | строка подключения к SQLite, по умолчанию `sqlite:///./data/app.db` |
| `BACKEND_CORS_ORIGINS` | разрешённые origin'ы для CORS (без `*`) |

## Запуск

Запускайте команду из каталога `backend/`, чтобы путь по умолчанию `DATABASE_URL`
(`sqlite:///./data/app.db`) указывал на `backend/data/app.db`:

```bash
uvicorn app.main:app --reload
```

API обслуживается под префиксом `/api`, например `GET http://127.0.0.1:8000/api/health`.

## Реализованные эндпоинты API

- `GET /api/health` — проверка доступности сервиса.
- `POST /api/documents` — создание документа (атомарно с записью аудита).
- `GET /api/documents` — список документов с фильтром `status`, пагинацией и сортировкой.
- `GET /api/documents/{document_id}` — получение документа по идентификатору.
- `GET /api/reviews` — список сохранённых проверок с фильтрами `document_id`,
  `needs_review`, `confidence`, `readiness`, пагинацией и сортировкой.
- `GET /api/reviews/{review_id}` — получение проверки по идентификатору.
- `GET /api/audit-runs` — список записей аудита с фильтрами `status`, `action`,
  `errors_only`, пагинацией и сортировкой.
- `GET /api/audit-runs/{audit_run_id}` — получение записи аудита по идентификатору.

Полное описание контрактов см. в `../docs/API_CONTRACTS.md`.

## Тестирование

```bash
pytest
```

Тесты выполняются на изолированной временной базе SQLite и не используют
`backend/data/app.db` и не обращаются к внешним сервисам. В частности, тесты
`tests/test_llm_client.py` и `tests/test_llm_prompts.py` не выполняют ни одного
реального HTTP-запроса к OpenAI: большинство используют инжектируемый fake-объект (или
ошибки SDK, поднятые напрямую в тесте), а несколько offline regression-тестов используют
настоящий `openai==2.53.0` с `httpx.MockTransport` вместо реальной сети. Ни один из
этих путей не требует `OPENAI_API_KEY` ни для запуска тестов, ни для CI.

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

Схема проверки, QC, клиент OpenAI и слой orchestration на этом этапе — это внутренний,
полностью протестированный слой, не подключённый ни к одному эндпоинту: запустить
настоящую ИИ-проверку через API пока нельзя.

**Ещё не реализовано на этом этапе** (сознательно вне рамок текущего этапа):

- эндпоинты запуска ИИ-проверки — `POST /api/documents/{document_id}/review` и
  `POST /api/ai/review`;
- workflow сохранения проверок, сгенерированных реальным ИИ-прогоном (persistence,
  репозитории, транзакции);
- audit для ИИ-операций (`document.review`, `ai.review`);
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
                      FinalReview, с fallback-путём при LLMClientError)
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

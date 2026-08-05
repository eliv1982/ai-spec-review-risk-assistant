# Backend

Бэкенд для проекта **AI Specification Review & Risk Assistant** — сервиса для проверки
технических спецификаций, требований к проекту, feature request'ов, автоматизационных
брифов и бизнес-требований. Подробности о продукте см. в `../PROJECT_SCOPE.md` и `../docs/`.

## Текущий этап

Реализован только фундамент бэкенда: слой персистентности и все эндпоинты создания/чтения/
списка, не связанные с ИИ. А именно:

- приложение FastAPI со стартапом (`lifespan`) и созданием схемы базы данных;
- модели SQLAlchemy для таблиц `documents`, `reviews`, `audit_runs`;
- атомарное создание документа вместе с записью аудита (`document.create`);
- эндпоинты чтения и списка для документов, проверок (`reviews`) и записей аудита, с
  фильтрацией, пагинацией и детерминированной сортировкой;
- конфигурация через переменные окружения;
- CORS, ограниченный списком настроенных origin'ов;
- автоматические тесты на изолированной временной базе SQLite.

**Ещё не реализовано на этом этапе** (сознательно вне рамок текущего этапа):

- клиент OpenAI и запуск LLM;
- детерминированная проверка качества (QC) и построение `FinalReview`;
- эндпоинт запуска проверки документа (`POST /api/documents/{document_id}/review`);
- отдельный демонстрационный эндпоинт `POST /api/ai/review`;
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
    enums.py          DocumentStatus, ReviewConfidence, ReviewReadiness, AuditStatus
    models.py         модели SQLAlchemy: Document, Review, AuditRun
    api/              роутеры: health, documents, reviews, audit_runs
    schemas/          Pydantic-схемы запросов/ответов и обёртка пагинации
    repositories/     операции персистентности для каждой таблицы
    services/         document_service (атомарное создание + аудит), audit_service (инвариант)
    utils/            utc_now_iso(), JSONText (сериализация JSON-колонок)
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

На этом этапе `OPENAI_API_KEY` не требуется для запуска приложения.

### Переменные окружения (`.env.example`)

| Переменная | Назначение |
| --- | --- |
| `OPENAI_API_KEY` | ключ OpenAI; не используется на текущем этапе |
| `OPENAI_MODEL` | название модели OpenAI; не используется на текущем этапе |
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
`backend/data/app.db` и не обращаются к внешним сервисам.

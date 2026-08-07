# Backend

FastAPI backend проекта **AI Specification Review & Risk Assistant**. Он принимает и
хранит документы, выполняет OpenAI Structured Outputs проверку, применяет
детерминированный QC, сохраняет `FinalReview`, ведёт аудит и формирует CSV-экспорты.

Общий Docker- и production-запуск описан в [корневом README](../README.md).

## Архитектура и конвейер

Backend — модульный монолит на FastAPI, SQLAlchemy 2, Pydantic v2 и SQLite:

```text
HTTP → FastAPI route → application service → repository → SQLite
                          ↓
                    ReviewOrchestrator
                          ↓
OpenAI Responses API → ModelReviewDraft → deterministic QC → FinalReview
```

- `app/api/` содержит тонкие HTTP-роутеры и сборку зависимостей.
- `app/llm/` выполняет синхронный нестриминговый вызов
  `responses.with_raw_response.parse(...)` с `text_format=ModelReviewDraft` и
  `store=False`.
- `ReviewOrchestrator` преобразует валидный draft через `build_final_review` или строит
  безопасный fallback только для типизированного `LLMClientError`.
- `ReviewWorkflow` атомарно сохраняет `Review`, обновляет `Document.status` и создаёт
  `AuditRun`.
- `AIReviewService` использует тот же конвейер без создания `Document`/`Review`, но с
  обязательным аудитом `ai.review`.
- `app/services/csv_export.py` формирует три CSV-экспорта только для чтения.

Версии, записываемые в AI-аудите:

```text
prompt_version = "spec-review-prompt-v2"
review_schema_version = "spec-review-schema-v1"
```

## Требования

- Python 3.11 или новее;
- зависимости из `requirements.txt`;
- для реальных AI-вызовов — действующие `OPENAI_API_KEY` и `OPENAI_MODEL`.

## Автономный запуск backend

Из корня репозитория создайте `.env`, если он ещё не создан:

```bash
cp .env.example .env
```

В PowerShell: `Copy-Item .env.example .env`.

Затем:

```bash
cd backend
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

macOS/Linux:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

API доступен по адресу `http://127.0.0.1:8000/api`; проверка доступности:

```bash
curl -fsS http://127.0.0.1:8000/api/health
```

Команду `uvicorn` нужно запускать из `backend/`, чтобы значение
`sqlite:///./data/app.db` указывало на `backend/data/app.db`.

## Переменные окружения

Backend читает корневой `.env`.

| Переменная | Значение по умолчанию | Назначение |
| --- | --- | --- |
| `OPENAI_API_KEY` | пусто | Обязательна для реального OpenAI-вызова; при отсутствии используется безопасный fallback. |
| `OPENAI_MODEL` | пусто | Обязательна для реального OpenAI-вызова; при отсутствии используется безопасный fallback. |
| `DATABASE_URL` | `sqlite:///./data/app.db` | Строка подключения SQLite. |
| `BACKEND_CORS_ORIGINS` | `http://localhost:5173` | Список разрешённых origin'ов через запятую; wildcard не используется. |

Конструирование приложения и `/api/health` не требуют ключа API: SDK-клиент создаётся
лениво только при фактическом вызове review endpoint'а.

## Каталог endpoint'ов

| Метод и путь | Назначение |
| --- | --- |
| `GET /api/health` | Проверка доступности. |
| `POST /api/documents` | Создание документа вместе с аудитом `document.create`. |
| `GET /api/documents` | Список документов с `status`, `limit`, `offset`. |
| `GET /api/documents/{document_id}` | Один документ. |
| `POST /api/documents/{document_id}/review` | Проверка документа и атомарное сохранение `Review` + `AuditRun`; успех и сохранённый fallback возвращают `201`. |
| `GET /api/reviews` | Список проверок с фильтрами и пагинацией. |
| `GET /api/reviews/export` | CSV всех проверок по фильтрам, без пагинации. |
| `GET /api/reviews/{review_id}` | Одна проверка. |
| `GET /api/reviews/{review_id}/export` | Подробный CSV одной проверки. |
| `POST /api/ai/review` | Проверка текста без `Document`/`Review`; создаётся только `AuditRun`. |
| `GET /api/audit-runs` | Журнал аудита с фильтрами и пагинацией. |
| `GET /api/audit-runs/export` | CSV аудита по фильтрам, без пагинации. |
| `GET /api/audit-runs/{audit_run_id}` | Одна запись аудита. |

Полные параметры, схемы и статусы: [API_CONTRACTS.md](../docs/API_CONTRACTS.md).

## Детерминированный QC

LLM возвращает только строгий `ModelReviewDraft`. Поля `needs_review` и
`review_reason_codes` модель не формирует и предложить не может. Backend строит
`FinalReview` и добавляет reason codes только по проверяемым условиям:

- `LOW_CONFIDENCE` — `confidence == "low"`;
- `TOO_VAGUE_INPUT` — нормализованный текст короче 200 символов или содержит меньше
  30 слов;
- `CONTRADICTORY_INPUT` — массив `contradictions` не пуст;
- `MISSING_ACCEPTANCE_CRITERIA` — массив `acceptance_criteria` пуст;
- `INSUFFICIENT_QUESTIONS` — вход расплывчатый и вопросов меньше трёх.

Коды дедуплицируются и сортируются в порядке каталога `ReviewReasonCode`.
`model_needs_review=true` может дать `needs_review=true` с пустым массивом
`review_reason_codes`. Полный нормативный контракт: [REVIEW_SCHEMA.md](../docs/REVIEW_SCHEMA.md).

## Безопасный fallback

`ReviewOrchestrator` перехватывает только типизированные ошибки LLM и сопоставляет их с
`MODEL_ERROR`, `INVALID_JSON` или `SCHEMA_MISMATCH`. Fallback содержит фиксированное
русское резюме, один фиксированный вопрос, пустые массивы находок,
`confidence="low"`, `document_readiness="not_ready"` и `needs_review=true`. Из
искусственных fallback-полей дополнительные содержательные коды не выводятся;
`TOO_VAGUE_INPUT` добавляется только по исходному тексту.

Сырые исключения, ответ провайдера, трассировка, ключи и полный текст документа не
попадают в `FinalReview`, пользовательское сообщение об ошибке или снимок аудита.

## Персистентность и аудит

Основные исходы `document.review`:

| Исход | `Review.error` | `AuditRun.status` | `Document.status` |
| --- | --- | --- | --- |
| Успех без ручной проверки | `null` | `success` | `reviewed` |
| Валидный результат с ручной проверкой | `null` | `needs_review` | `reviewed` |
| Сохранённый технический fallback | фиксированное очищенное сообщение | `error` | `review_failed` |

Все три изменения одной сохранённой проверки фиксируются атомарно. Если пригодный
`Review` сохранить нельзя, основная транзакция откатывается, а отдельная recovery-
транзакция по возможности переводит документ в `review_failed` и пишет аудит ошибки.
Сбой самой recovery-транзакции не подменяет исходное исключение и не оставляет
частичных recovery-изменений.

Данные аудита содержат только безопасные метаданные. `document.create` записывает длины
полей, `document.review` — идентификаторы, литералы версий и fallback-метаданные,
`ai.review` — длины полей, version literals, настроенное имя модели и итоговые флаги.
Полные `title`/`text`, `review_json`, ключ API и ответ провайдера в `audit_runs` не
записываются. Точная структура приведена в [DATA_MODEL.md](../docs/DATA_MODEL.md).

CSV-экспорт использует UTF-8 с BOM, `;`, `\r\n`, статические ASCII-имена файлов и
нейтрализацию formula injection. Экспорт не создаёт записей аудита.

## Тесты

```bash
cd backend
pytest
```

На принятом release `HEAD` обнаруживается 582 backend-теста; последняя полная проверка
перед production-развёртыванием завершилась результатом `582 passed`. Тесты используют
временную SQLite и тестовые клиенты либо `httpx.MockTransport`; реальный OpenAI API и
`OPENAI_API_KEY` им не нужны.

Полный локальный Docker-запуск, frontend и схема production-развёртывания описаны в
[корневом README](../README.md).

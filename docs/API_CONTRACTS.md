# API-контракты

Все временные метки — канонические строки UTC ISO 8601 с завершающим `Z`, например
`2026-08-04T18:30:00Z`. Все идентификаторы ресурсов — строки UUID. Тела запросов и
ответов используют JSON, кроме явно обозначенных CSV-ответов.

Обычная error envelope:

```json
{
  "detail": "Понятное сообщение об ошибке"
}
```

HTTP `422` от FastAPI/Pydantic может содержать массив `detail`.

## Общие правила валидации

- отсутствующее, невалидное, пустое после trim или неверно типизированное обязательное
  поле возвращает HTTP `422`;
- невалидный UUID в параметре пути или запроса возвращает `422`;
- для этих случаев API не использует `400`;
- непредвиденная необработанная ошибка возвращает `500` с очищенным сообщением без
  подробностей исключения.

## Пагинация list endpoint'ов

| Параметр | По умолчанию | Минимум | Максимум |
| --- | --- | --- | --- |
| `limit` | `50` | `1` | `100` |
| `offset` | `0` | `0` | нет |

Сортировка: `created_at DESC`, затем `id DESC` как детерминированный tie-breaker.

```text
total = число строк после всех фильтров, но до limit и offset
```

`total` не равен размеру текущей страницы и не обязан равняться размеру таблицы без
фильтров. Выход за допустимые границы и неверный тип дают `422`.

CSV endpoint'ы не принимают `limit`/`offset` и экспортируют все строки по активным
фильтрам.

## Имена reason codes

- SQLite-колонка: `reason_codes_json`, текст JSON с массивом.
- JSON API: `reason_codes`, обычный массив JSON.
- Внутри `FinalReview`: `review_reason_codes`.
- CSV показывает русские подписи в колонке «Причины экспертной проверки», а не исходные
  значения enum.

Клиент JSON API никогда не получает имя `reason_codes_json`.

## Общий CSV-контракт

Доступны три эндпоинта только для чтения:

- `GET /api/reviews/export`;
- `GET /api/reviews/{review_id}/export`;
- `GET /api/audit-runs/export`.

Общие правила:

- кодировка: UTF-8 с BOM (`UTF-8-SIG`);
- разделитель: `;`;
- окончания строк: `\r\n`;
- runtime `Content-Type`: `text/csv; charset=utf-8`; в OpenAPI `200` документирован как
  `text/csv`, а ответ об ошибке валидации `422` остаётся `application/json`;
- `Content-Disposition`: `attachment` со статическим ASCII-именем файла:
  `reviews-export.csv`, `audit-runs-export.csv` или `review-{review_id}.csv`;
- переданный пользователем `title` никогда не используется как имя файла;
- пагинации нет, сортировка совпадает с соответствующим list endpoint;
- пустая выборка возвращает `200`, BOM и только строку заголовков;
- экспорт не вызывает LLM, не меняет состояние предметной области и не создаёт
  `audit_runs` ни при
  успехе, ни при ошибке.

### Защита от formula injection

Для каждой строковой ячейки определяется первый значимый символ после пропуска только
обычных ASCII-пробелов (`" "`). Если это `=`, `+`, `-`, `@`, табуляция, возврат каретки
или перевод строки, к исходному значению целиком добавляется ведущий апостроф `'`.
Пробелы и управляющий символ не удаляются. Значение, уже начинающееся с `'`, не изменяется
повторно. Символ `/` не является trigger.

Защита применяется ко всем текстовым значениям пользователя и модели, включая название
документа, `error` и ячейку с деталями JSON, и меняет только CSV-представление, а не
значение в SQLite.

---

## `GET /api/health`

Проверяет доступность FastAPI-процесса.

Параметров и тела нет.

Успех — `200`:

```json
{
  "status": "ok"
}
```

Операция не создаёт domain records и не журналируется.

---

## `POST /api/documents`

Создаёт plain-text документ.

Тело запроса:

```json
{
  "title": "Требования к уведомлениям",
  "text": "Полный текст документа"
}
```

| Поле | Обязательно | Правило |
| --- | --- | --- |
| `title` | да | String, непустая после trim. |
| `text` | да | String, непустая после trim. |

Успех — `201`:

```json
{
  "id": "uuid",
  "created_at": "2026-08-04T18:30:00Z",
  "title": "Требования к уведомлениям",
  "text": "Полный текст документа",
  "status": "created"
}
```

`Document` и `AuditRun` фиксируются атомарно. Данные аудита:

```json
{
  "action": "document.create",
  "entity_type": "document",
  "entity_id": "uuid",
  "input_json": {
    "title_length": 25,
    "text_length": 22
  },
  "output_json": {
    "document_id": "uuid",
    "status": "created"
  },
  "status": "success",
  "error": null
}
```

| Код | Причина |
| --- | --- |
| `422` | Отсутствующие, пустые, неверно типизированные поля. |
| `500` | Непредвиденный сбой, включая невозможность сохранить обязательный аудит. |

Создаёт строки `documents` и `audit_runs`.

---

## `GET /api/documents`

Возвращает документы с фильтром и пагинацией.

| Параметр запроса | Тип | Обязательно | Описание |
| --- | --- | --- | --- |
| `status` | enum | нет | `created` \| `reviewed` \| `review_failed` |
| `limit` | integer | нет | `1..100`, по умолчанию `50` |
| `offset` | integer | нет | `>= 0`, по умолчанию `0` |

Успех — `200`:

```json
{
  "items": [
    {
      "id": "uuid",
      "created_at": "2026-08-04T18:30:00Z",
      "title": "Требования к уведомлениям",
      "text": "Полный текст документа",
      "status": "created"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

Невалидные значения параметров запроса дают `422`; непредвиденный сбой — `500`.
Эндпоинт предназначен только для чтения и не создаёт записи аудита или предметной области.

---

## `GET /api/documents/{document_id}`

Возвращает документ по UUID. Успешный `200` имеет форму одного элемента из списка.

| Код | Причина |
| --- | --- |
| `404` | Документ не найден. |
| `422` | `document_id` не является UUID. |
| `500` | Непредвиденный сбой. |

Эндпоинт предназначен только для чтения и не создаёт записи аудита или предметной области.

---

## `POST /api/documents/{document_id}/review`

Запускает полный конвейер для сохранённого документа и сохраняет результат. Параметр
пути `document_id` — обязательный UUID. Тела запроса нет.

Успех — `201`:

```json
{
  "id": "uuid",
  "created_at": "2026-08-04T18:30:00Z",
  "document_id": "uuid",
  "review_json": {
    "summary": "Краткое заключение",
    "risks": [],
    "missing_requirements": [],
    "contradictions": [],
    "questions_to_client": [],
    "acceptance_criteria": ["Если выполнено условие, когда происходит действие, то получен измеримый результат."],
    "confidence": "medium",
    "document_readiness": "needs_clarification",
    "needs_review": false,
    "review_reason_codes": []
  },
  "confidence": "medium",
  "readiness": "needs_clarification",
  "needs_review": false,
  "reason_codes": [],
  "error": null
}
```

`review_json` — полный `FinalReview` из [REVIEW_SCHEMA.md](REVIEW_SCHEMA.md).
`model_needs_review` не возвращается.

| Top-level поле | Источник |
| --- | --- |
| `confidence` | `review_json.confidence` |
| `readiness` | `review_json.document_readiness` |
| `needs_review` | `review_json.needs_review` |
| `reason_codes` | `review_json.review_reason_codes` |

### Матрица персистентности и статусов

| Исход | `Review.error` | `AuditRun.status` | `AuditRun.error` | `Document.status` | HTTP |
| --- | --- | --- | --- | --- | --- |
| Валидный результат, `needs_review=false` | `null` | `success` | `null` | `reviewed` | `201` |
| Валидный результат, `needs_review=true` | `null` | `needs_review` | `null` | `reviewed` | `201` |
| `used_fallback=true`, основная транзакция зафиксирована | непустое фиксированное очищенное сообщение | `error` | то же сообщение | `review_failed` | `201` |
| Пригодный `Review` не создан, recovery committed | строки нет | `error` | непустое фиксированное сообщение | `review_failed` | `500` |
| Пригодный `Review` не создан, recovery тоже неуспешна | строки нет | новой строки нет | не применимо | прежний статус | `500` |

Для отсутствующего документа эндпоинт возвращает `404`; первоначальный `404` не вызывает LLM и
не создаёт аудит. Если документ удалён между первоначальным чтением и write-
транзакцией, также возвращается `404`, основная транзакция откатывается и аудит не
создаётся.

Сохранённый fallback — технический сбой, безопасно локализованный backend. Он содержит
пригодный `FinalReview`, поэтому возвращает `201`, но не считается `reviewed`.
Фиксированное сообщение для пользователя:

```text
Проверку не удалось выполнить автоматически. Результат требует экспертной проверки.
```

Конкретная категория не включается в это сообщение и хранится только в
`AuditRun.output_json.llm_error_category`.

`needs_review=true` сам по себе техническим сбоем не является. Единственный надёжный
признак fallback внутри прикладного процесса — `used_fallback`.

### Граница recovery

Если orchestration, QC, проверка результата или основная персистентность неожиданно
завершаются ошибкой, основная транзакция полностью откатывается. Затем отдельная
recovery-транзакция пытается
атомарно выставить `Document.status="review_failed"` и создать один
`AuditRun(status="error", entity_type="document")`.

Recovery выполняется по возможности. При её собственном сбое оба recovery-изменения
откатываются; ошибка recovery не подменяет исходное исключение. Поэтому в этом крайнем
случае статус может остаться `created`, `reviewed` или `review_failed` от предыдущей
попытки, а аудит текущей попытки отсутствует.

### Данные аудита

Для сохранённого результата:

```json
{
  "action": "document.review",
  "entity_type": "review",
  "entity_id": "review-uuid",
  "input_json": {
    "document_id": "document-uuid",
    "prompt_version": "spec-review-prompt-v2",
    "review_schema_version": "spec-review-schema-v1"
  },
  "output_json": {
    "review_id": "review-uuid",
    "used_fallback": false,
    "llm_error_category": null
  }
}
```

Recovery-аудит использует `entity_type="document"`, `entity_id=document_id`, тот же
`input_json` и `output_json=null`. Полный document text, `review_json` и имя модели в
аудит этой операции не записываются.

| Код | Причина |
| --- | --- |
| `404` | Документ не найден. |
| `422` | Невалидный `document_id`. |
| `500` | Непредвиденный сбой или невозможность сохранить пригодный `Review`/обязательный аудит. |

Создаёт `reviews`, обновляет `documents.status` и создаёт `audit_runs`, если основная
транзакция успешно сохраняет результат. Гарантии recovery описаны выше.

---

## `GET /api/reviews`

Возвращает сохранённые проверки.

| Параметр запроса | Тип | Обязательно | Описание |
| --- | --- | --- | --- |
| `document_id` | UUID | нет | Фильтр по документу. |
| `needs_review` | boolean | нет | Фильтр по итоговому backend-флагу. |
| `confidence` | enum | нет | `high` \| `medium` \| `low` |
| `readiness` | enum | нет | `ready` \| `needs_clarification` \| `not_ready` |
| `limit` | integer | нет | `1..100`, по умолчанию `50` |
| `offset` | integer | нет | `>= 0`, по умолчанию `0` |

Успех — `200`:

```json
{
  "items": [
    {
      "id": "uuid",
      "created_at": "2026-08-04T18:30:00Z",
      "document_id": "uuid",
      "review_json": {},
      "confidence": "low",
      "readiness": "not_ready",
      "needs_review": true,
      "reason_codes": ["LOW_CONFIDENCE", "TOO_VAGUE_INPUT"],
      "error": null
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

В реальном ответе `review_json` — полный валидный `FinalReview`; `{}` здесь только
сокращает иллюстрацию list envelope. `model_needs_review` отсутствует.

Невалидные фильтры, UUID и пагинация дают `422`; непредвиденный сбой — `500`.
Эндпоинт предназначен только для чтения и не создаёт аудит.

---

## `GET /api/reviews/export`

Экспортирует все проверки по фильтрам `document_id`, `needs_review`, `confidence`,
`readiness`. `limit` и `offset` не принимаются. Static route зарегистрирован перед
`/{review_id}`. Успех — `200` и:

```text
Content-Disposition: attachment; filename="reviews-export.csv"
```

Колонки:

| Колонка | Источник и отображение |
| --- | --- |
| ID проверки | `review.id`, UUID без локализации |
| ID документа | `review.document_id`, UUID без локализации |
| Название документа | `document.title`, загружается одним JOIN |
| Дата проверки | `created_at` → московское время `ДД.ММ.ГГГГ, ЧЧ:ММ` |
| Нужна экспертная проверка | `Да` / `Нет` |
| Уверенность анализа | `high`→`Высокая`, `medium`→`Средняя`, `low`→`Низкая` |
| Статус готовности | `ready`→`Готов`, `needs_clarification`→`Требует уточнений`, `not_ready`→`Не готов` |
| Причины экспертной проверки | Русские подписи через `\|` в порядке каталога |
| Ошибка | Очищенный `review.error` или пустая строка |

Нераспознанное значение enum отображается без локализации, а не вызывает ошибку. Полный
`review_json` намеренно отсутствует; для него используется подробный export.

Невалидные фильтры дают `422`; непредвиденный сбой — `500`. Эндпоинт предназначен
только для чтения и не создаёт аудит.

---

## `GET /api/reviews/{review_id}`

Возвращает одну сохранённую проверку в форме элемента списка. `review_json` —
`FinalReview`, поле `reason_codes` — обычный массив, `model_needs_review` отсутствует.

| Код | Причина |
| --- | --- |
| `404` | Проверка не найдена. |
| `422` | `review_id` не является UUID. |
| `500` | Непредвиденный сбой. |

Эндпоинт предназначен только для чтения и не создаёт аудит.

---

## `GET /api/reviews/{review_id}/export`

Возвращает подробный двухколоночный CSV «Поле» / «Значение».

Успех — `200`:

```text
Content-Disposition: attachment; filename="review-{review_id}.csv"
```

| Поле | Значение |
| --- | --- |
| ID проверки | `review.id`, UUID без локализации |
| ID документа | `review.document_id`, UUID без локализации |
| Название документа | `document.title` или пустая строка, если родительский документ недоступен |
| Дата проверки | Московское время `ДД.ММ.ГГГГ, ЧЧ:ММ` |
| Нужна экспертная проверка | `Да` / `Нет` |
| Уверенность анализа | Локализованное значение `confidence` |
| Статус готовности | Локализованное значение `readiness` |
| Причины экспертной проверки | Русские подписи через `\|` |
| Ошибка | Очищенный `review.error` или пустая строка |
| Полный результат JSON | Полный `FinalReview` как одна детерминированная строка JSON с `ensure_ascii=false` и сортировкой ключей |

`model_needs_review` в полном JSON отсутствует. Невалидный UUID даёт `422`,
неизвестная проверка — `404`, непредвиденный сбой — `500`. Эндпоинт предназначен
только для чтения и не создаёт аудит.

---

## `POST /api/ai/review`

Проверяет произвольный текст без создания `Document` или `Review`.

Тело запроса:

```json
{
  "title": "Модуль уведомлений",
  "text": "Текст требований"
}
```

| Поле | Обязательно | Правило |
| --- | --- | --- |
| `title` | нет | Метка для аудита; поле можно опустить. Если передано, должно быть непустой после trim строкой. Явный JSON `null` запрещён. |
| `text` | да | Непустая после trim string. |

Лишние поля запрещены (`extra="forbid"`).

Успех — `200`:

```json
{
  "review_json": {
    "summary": "Краткое заключение",
    "risks": [],
    "missing_requirements": [],
    "contradictions": [],
    "questions_to_client": [],
    "acceptance_criteria": ["Если выполнено условие, когда происходит действие, то получен измеримый результат."],
    "confidence": "medium",
    "document_readiness": "needs_clarification",
    "needs_review": false,
    "review_reason_codes": []
  },
  "confidence": "medium",
  "readiness": "needs_clarification",
  "needs_review": false,
  "reason_codes": [],
  "error": null
}
```

Последовательность: валидация → OpenAI Structured Outputs → `ModelReviewDraft` → Pydantic →
детерминированный QC → `FinalReview` или безопасный fallback → фиксация аудита → ответ.
`model_needs_review` не возвращается.

При типизированном LLM-сбое endpoint возвращает `200` с безопасным `FinalReview`,
`needs_review=true` и `error=null` в теле HTTP-ответа. Технический сбой отмечается не
полем `error` ответа, а обязательным `AuditRun.status="error"` с фиксированным непустым
`AuditRun.error`. Строки `documents` и `reviews` не создаются.

### Данные аудита

```json
{
  "action": "ai.review",
  "entity_type": null,
  "entity_id": null,
  "input_json": {
    "title_length": 20,
    "text_length": 17,
    "prompt_version": "spec-review-prompt-v2",
    "review_schema_version": "spec-review-schema-v1",
    "model": "configured-model-name"
  },
  "output_json": {
    "used_fallback": false,
    "llm_error_category": null,
    "needs_review": false,
    "review_reason_codes": []
  }
}
```

При опущенном `title` значение `title_length` равно `null`; пустое настроенное имя
модели превращается в `model=null`. Полные `title`/`text` и `FinalReview` в аудит не
попадают. Recovery-аудит при непредвиденном сбое сохраняет тот же `input_json`, но
`output_json=null`.

| Исход | `AuditRun.status` | `AuditRun.error` |
| --- | --- | --- |
| Валидный результат, `needs_review=false` | `success` | `null` |
| Валидный результат, `needs_review=true` | `needs_review` | `null` |
| Безопасный fallback | `error` | непустое фиксированное очищенное сообщение |

| Код | Причина |
| --- | --- |
| `422` | Невалидное тело, включая пустые `text`/`title`, явный `title:null` или лишнее поле. |
| `500` | Непредвиденный сбой, включая невозможность сохранить обязательный аудит. |

Создаёт только `audit_runs`.

---

## `GET /api/audit-runs`

Возвращает записи аудита.

| Параметр запроса | Тип | Обязательно | Описание |
| --- | --- | --- | --- |
| `status` | enum | нет | `success` \| `needs_review` \| `error` |
| `action` | string | нет | Точное имя операции; пустое после trim запрещено. |
| `errors_only` | boolean | нет | При `true` только `status == "error"`; по умолчанию `false`. |
| `limit` | integer | нет | `1..100`, по умолчанию `50` |
| `offset` | integer | нет | `>= 0`, по умолчанию `0` |

`status` и `errors_only` можно передать вместе; фильтры объединяются через `AND`.

Успех — `200`:

```json
{
  "items": [
    {
      "id": "uuid",
      "created_at": "2026-08-04T18:30:00Z",
      "action": "document.review",
      "entity_type": "review",
      "entity_id": "uuid",
      "input_json": {},
      "output_json": {},
      "status": "needs_review",
      "error": null,
      "duration_ms": 1234
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

Невалидные фильтры/пагинация и пустой `action` дают `422`; непредвиденный сбой —
`500`. Эндпоинт предназначен только для чтения; чтение аудита не журналируется.

---

## `GET /api/audit-runs/export`

Экспортирует все записи аудита по фильтрам `status`, `action`, `errors_only`, без
пагинации. Комбинация `status` и `errors_only` допустима и использует `AND`. Статический
маршрут зарегистрирован перед `/{audit_run_id}`.

Успех — `200`:

```text
Content-Disposition: attachment; filename="audit-runs-export.csv"
```

| Колонка | Источник и отображение |
| --- | --- |
| ID записи | `audit_run.id`, UUID без локализации |
| Операция | `document.create`→`Создание документа`, `document.review`→`Проверка документа`, `ai.review`→`Проверка текста без сохранения` |
| Тип объекта | `document`→`Документ`, `review`→`Проверка`, `null`→пусто |
| ID объекта | UUID без локализации или пусто |
| Статус | `success`→`Успешно`, `needs_review`→`Нужна экспертная проверка`, `error`→`Техническая ошибка` |
| Длительность | `<1000` → `14 мс`; `>=1000` → `37,0 с` с одним десятичным знаком |
| Ошибка | Очищенный `error` или пустая строка |
| Дата и время | Московское время `ДД.ММ.ГГГГ, ЧЧ:ММ` |
| Детали JSON | `{"input_json": ..., "output_json": ...}` как одна детерминированная строка JSON |

Нераспознанное значение enum/action/entity отображается без локализации.
Невалидные фильтры и пустой `action` дают `422`; непредвиденный сбой — `500`.
Эндпоинт предназначен только для чтения и не создаёт аудит.

---

## `GET /api/audit-runs/{audit_run_id}`

Возвращает одну запись аудита в форме элемента списка.

| Код | Причина |
| --- | --- |
| `404` | Запись аудита не найдена. |
| `422` | `audit_run_id` не является UUID. |
| `500` | Непредвиденный сбой. |

Эндпоинт предназначен только для чтения; дополнительный аудит не создаётся.

## Каталог операций аудита

| Операция | Эндпоинт | Записи | Связь с сущностью |
| --- | --- | --- | --- |
| `document.create` | `POST /api/documents` | `documents` + `audit_runs` | `document` / ID документа |
| `document.review` | `POST /api/documents/{document_id}/review` | `reviews` + обновление статуса + `audit_runs`, если результат пригоден | `review` / ID проверки; при recovery `document` / ID документа |
| `ai.review` | `POST /api/ai/review` | только `audit_runs` | `null` / `null` |

Проверка доступности, эндпоинты списка/детали и все CSV-экспорты не журналируются.

## Значения статуса аудита

| Статус | Смысл |
| --- | --- |
| `success` | Технического сбоя нет, экспертная проверка не нужна. |
| `needs_review` | `ModelReviewDraft` успешно разобран и валидирован, но итоговый результат требует эксперта. |
| `error` | Сбой модели, транспорта, JSON, схемы или персистентности, включая безопасный fallback. |

Инварианты:

- `status="error"` требует непустой очищенный `error`;
- `status="success"` и `status="needs_review"` требуют `error=null`;
- `errors_only=true` означает ровно `status == "error"`, а не проверку nullable-поля;
- строки, нарушающие инвариант, не считаются валидными.

## Связанные контракты

- [Схема `ModelReviewDraft` / `FinalReview`](REVIEW_SCHEMA.md)
- [Модель SQLite и точные снимки аудита](DATA_MODEL.md)
- [Архитектура и транзакционные границы](ARCHITECTURE.md)

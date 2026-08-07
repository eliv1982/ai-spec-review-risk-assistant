# Схема проверки

Документ определяет две разные строгие схемы:

1. **`ModelReviewDraft`** — недоверенный ответ OpenAI Structured Outputs, который
   Pydantic валидирует до детерминированного QC.
2. **`FinalReview`** — объект, создаваемый backend, сохраняемый в
   `reviews.review_json` и возвращаемый API.

Поля `needs_review` и `review_reason_codes` формирует только backend. LLM не может
предлагать, выбирать или сохранять reason codes.

## A. `ModelReviewDraft`

| Поле | Тип | Обязательно | Описание |
| --- | --- | --- | --- |
| `summary` | string | да | Краткое заключение. |
| `risks` | array of `Risk` | да | Риски; может быть пустым. |
| `missing_requirements` | array of `MissingRequirement` | да | Пробелы; может быть пустым. |
| `contradictions` | array of `Contradiction` | да | Противоречия; может быть пустым. |
| `questions_to_client` | `array[string]` | да | Уточняющие вопросы; может быть пустым. |
| `acceptance_criteria` | `array[string]` | да | Измеримые критерии; может быть пустым. |
| `confidence` | enum | да | Уверенность модели. |
| `document_readiness` | enum | да | Предложенная моделью готовность документа. |
| `model_needs_review` | strict boolean | да | Предложенный моделью флаг ручной проверки. |

Правила:

- `ModelReviewDraft` не содержит `needs_review` или `review_reason_codes`;
- `model_needs_review` принимает только настоящее логическое значение JSON, без приведения строк или
  чисел;
- top-level и все вложенные объекты используют `extra="forbid"`;
- draft никогда не сохраняется как `reviews.review_json` и не возвращается API.

### Валидация строк

Pydantic выполняет trim каждой обязательной строки и отклоняет пустое значение. Правило
действует для:

- `summary`;
- `risks[].description`;
- `risks[].evidence`, если это не `null`;
- `missing_requirements[].description`;
- `contradictions[].description`;
- каждого элемента `contradictions[].evidence`;
- каждого элемента `questions_to_client`;
- каждого элемента `acceptance_criteria`.

Пустая после trim строка приводит к fallback с `SCHEMA_MISMATCH`, а не к успешной
проверке. Пустые массивы разрешены там, где это указано схемой.

## B. `FinalReview`

| Поле | Тип | Обязательно | Описание |
| --- | --- | --- | --- |
| `summary` | string | да | Из draft или фиксированного шаблона fallback. |
| `risks` | `array[Risk]` | да | Из draft; в fallback пустой. |
| `missing_requirements` | `array[MissingRequirement]` | да | Из draft; в fallback пустой. |
| `contradictions` | `array[Contradiction]` | да | Из draft; в fallback пустой. |
| `questions_to_client` | `array[string]` | да | Из draft или фиксированного шаблона fallback. |
| `acceptance_criteria` | `array[string]` | да | Из draft; в fallback пустой. |
| `confidence` | enum | да | Из draft или `low` в fallback. |
| `document_readiness` | enum | да | Из draft или `not_ready` в fallback. |
| `needs_review` | `StrictBool` | да | Только backend. |
| `review_reason_codes` | `array[ReviewReasonCode]` | да | Только backend. |

`FinalReview` не содержит `model_needs_review`, запрещает лишние поля и используется в
JSON-ответах, `reviews.review_json` и ячейке «Полный результат JSON» подробного CSV.

## Вложенные типы

### `Risk`

| Поле | Тип | Обязательно | Nullable |
| --- | --- | --- | --- |
| `severity` | `low` \| `medium` \| `high` | да | нет |
| `category` | `RiskCategory` | да | нет |
| `description` | string | да | нет |
| `evidence` | string \| null | да | да; `null`, если прямого фрагмента нет |

### `MissingRequirement`

| Поле | Тип | Обязательно | Nullable |
| --- | --- | --- | --- |
| `category` | `RiskCategory` | да | нет |
| `description` | string | да | нет |

### `Contradiction`

| Поле | Тип | Обязательно | Nullable |
| --- | --- | --- | --- |
| `description` | string | да | нет |
| `evidence` | `array[string]` | да | нет; массив может быть пустым |

Во всех трёх типах лишние поля запрещены.

## Значения enum

### `RiskCategory`

Закрытый enum для рисков и недостающих требований:

| Значение |
| --- |
| `scope` |
| `functionality` |
| `data` |
| `integration` |
| `security` |
| `privacy` |
| `performance` |
| `reliability` |
| `usability` |
| `operations` |
| `acceptance` |
| `timeline` |
| `dependency` |
| `compliance` |
| `other` |

### `confidence`

| Значение | Смысл |
| --- | --- |
| `high` | В исходном тексте достаточно сильных подтверждений и мало неоднозначности. |
| `medium` | Есть частичная неоднозначность или недостающие детали. |
| `low` | Основание для выводов слабое, расплывчатое или ненадёжное. |

### `document_readiness`

| Значение | Смысл |
| --- | --- |
| `ready` | Документа достаточно для планирования реализации при небольших пробелах. |
| `needs_clarification` | До продолжения необходимо получить ответы на ключевые вопросы. |
| `not_ready` | Существенные пробелы или противоречия блокируют готовность. |

### `review_reason_codes`

Это закрытый backend-only каталог. Порядок ниже является обязательным порядком
нормализации:

| Порядок | Код | Класс | Точное условие |
| --- | --- | --- | --- |
| 1 | `LOW_CONFIDENCE` | content-derived | `confidence == "low"` в валидном `ModelReviewDraft`. |
| 2 | `TOO_VAGUE_INPUT` | содержательный (`content-derived`) или дополнительный в fallback | Исходный текст не проходит точные пороги расплывчатости. |
| 3 | `CONTRADICTORY_INPUT` | содержательный (`content-derived`) | `len(contradictions) > 0` в валидном draft. |
| 4 | `MISSING_ACCEPTANCE_CRITERIA` | содержательный (`content-derived`) | `acceptance_criteria` пуст в валидном draft. |
| 5 | `INSUFFICIENT_QUESTIONS` | content-derived | Текст расплывчатый и `len(questions_to_client) < 3`. |
| 6 | `INVALID_JSON` | источник сбоя (`failure-provenance`) | Ответ нельзя разобрать как JSON. |
| 7 | `SCHEMA_MISMATCH` | источник сбоя (`failure-provenance`) | Разобранные данные не соответствуют строгой Pydantic-схеме. |
| 8 | `MODEL_ERROR` | источник сбоя (`failure-provenance`) | Сбой конфигурации, провайдера, API, транспорта или вызова модели. |

`MODEL_ERROR`, `INVALID_JSON`, `SCHEMA_MISMATCH` не появляются на пути успешно
валидированного draft.

## Точное определение расплывчатости

```text
normalized_text = " ".join(text.split())

too_vague =
  len(normalized_text) < 200
  OR len(normalized_text.split(" ")) < 30
```

Пустая нормализованная строка всегда расплывчата. Других application-defined эвристик
для этого признака нет.

## Построение `FinalReview` из валидного draft

```text
deterministic_reason_codes =
  коды, точные backend-условия которых выполнились

final_needs_review =
  model_review_draft.model_needs_review
  OR len(deterministic_reason_codes) > 0

final_review.review_reason_codes =
  deterministic_reason_codes
```

Backend заново формирует список только из подтверждённых условий, дедуплицирует и
сортирует его в порядке каталога. Модель не возвращает список, поэтому модельные коды
не копируются, не фильтруются и не объединяются.

### Условия успешного пути

| Код | Точное условие |
| --- | --- |
| `LOW_CONFIDENCE` | Только `confidence == "low"`. |
| `TOO_VAGUE_INPUT` | Только исходный текст не проходит указанные пороги. |
| `CONTRADICTORY_INPUT` | Только `len(contradictions) > 0`. |
| `MISSING_ACCEPTANCE_CRITERIA` | Только пустой `acceptance_criteria`. |
| `INSUFFICIENT_QUESTIONS` | Только расплывчатый вход и меньше трёх вопросов. |

Если `model_needs_review=true`, но ни одно детерминированное условие не сработало:

```json
{
  "needs_review": true,
  "review_reason_codes": []
}
```

Новый код для объяснения модельного флага не добавляется. Аудит для такого результата:
`status="needs_review"`, `error=null`.

Если `final_needs_review=false`, массив `review_reason_codes` обязан быть пустым.
Содержательные (`content-derived`) коды не выводятся из искусственных fallback-полей.

## Источник технического сбоя (`failure-provenance`) и безопасный fallback

| Причина | Корневой код |
| --- | --- |
| Сбой конфигурации, провайдера, API, транспорта или вызова модели | `MODEL_ERROR` |
| Ответ не разбирается как JSON | `INVALID_JSON` |
| JSON не соответствует `ModelReviewDraft`, включая пустую обязательную строку | `SCHEMA_MISMATCH` |

Нормативный fallback из текущей реализации:

```json
{
  "summary": "Автоматическая проверка не может быть выполнена надёжно. Требуется ручная проверка.",
  "risks": [],
  "missing_requirements": [],
  "contradictions": [],
  "questions_to_client": [
    "Можете ли вы предоставить более полный и конкретный документ с требованиями?"
  ],
  "acceptance_criteria": [],
  "confidence": "low",
  "document_readiness": "not_ready",
  "needs_review": true,
  "review_reason_codes": ["MODEL_ERROR"]
}
```

Точные строки `summary` и единственного вопроса выше совпадают с
`backend/app/services/review_qc.py`.

| Технический исход | Обязательный корневой код | Дополнительный код |
| --- | --- | --- |
| Сбой модели/API/транспорта/конфигурации/провайдера | `MODEL_ERROR` | `TOO_VAGUE_INPUT`, если исходный текст расплывчатый |
| Сбой разбора JSON | `INVALID_JSON` | `TOO_VAGUE_INPUT`, если исходный текст расплывчатый |
| Сбой валидации схемы | `SCHEMA_MISMATCH` | `TOO_VAGUE_INPUT`, если исходный текст расплывчатый |

Итоговый массив всегда сортируется по каталогу. Поэтому для расплывчатого входа
`TOO_VAGUE_INPUT` располагается перед `INVALID_JSON`, `SCHEMA_MISMATCH` или
`MODEL_ERROR`, несмотря на то что технический код остаётся корневой причиной.

Fallback всегда имеет:

- `needs_review=true`;
- `confidence="low"`;
- `document_readiness="not_ready"`;
- пустые `risks`, `missing_requirements`, `contradictions`, `acceptance_criteria`;
- ровно один фиксированный вопрос;
- отсутствие выдуманных domain findings;
- отсутствие `LOW_CONFIDENCE`, `MISSING_ACCEPTANCE_CRITERIA`,
  `INSUFFICIENT_QUESTIONS`, `CONTRADICTORY_INPUT`, выведенных из искусственных полей.

## Семантика сохранённого fallback

Если fallback успешно сохраняется для проверки документа:

- создаётся `Review` с валидным fallback в `review_json`;
- `Review.needs_review=true`;
- `Review.error` содержит точную фиксированную строку
  `Проверку не удалось выполнить автоматически. Результат требует экспертной проверки.`;
- `AuditRun.status="error"`, а `AuditRun.error` содержит ту же строку;
- `AuditRun.output_json.llm_error_category` хранит отдельную безопасную техническую
  категорию;
- `Document.status="review_failed"`;
- endpoint возвращает HTTP `201`, поскольку пригодный `Review` сохранён.

Необработанное исключение, его сообщение, трассировка, ответ провайдера и значение
`LLMErrorCategory` не попадают в предназначенные пользователю
`Review.error`/`AuditRun.error`.

Успешно валидированный результат с `needs_review=true` — другой исход:

- `Review.error=null`;
- `AuditRun.status="needs_review"`;
- `AuditRun.error=null`;
- `Document.status="reviewed"`.

Технический fallback определяется по `used_fallback`, а не по `needs_review`,
`confidence`, `readiness` или reason codes.

## Версии prompt и схемы

```text
prompt_version = "spec-review-prompt-v2"
review_schema_version = "spec-review-schema-v1"
```

Это прикладные константы внутри снимка AI-аудита, а не колонки БД. Материальное
изменение prompt или review schema требует нового литерала версии.

## Пример `ModelReviewDraft`

```json
{
  "summary": "В брифе описана функция уведомлений, но не определены хранение данных и обработка сбоев.",
  "risks": [
    {
      "severity": "high",
      "category": "reliability",
      "description": "Для неуспешной доставки не определены повторные попытки и очередь недоставленных сообщений.",
      "evidence": "При наступлении события система отправляет пользователю уведомление."
    }
  ],
  "missing_requirements": [
    {
      "category": "data",
      "description": "Не указан срок хранения истории уведомлений."
    }
  ],
  "contradictions": [],
  "questions_to_client": [
    "Каков срок хранения истории уведомлений?",
    "Нужно ли повторять неуспешную доставку и по какой политике?"
  ],
  "acceptance_criteria": [
    "Если пользователь подписан на уведомления, когда наступает подтверждённое событие, то система доставляет ровно одно уведомление в течение 60 секунд.",
    "Если доставка завершилась ошибкой, когда попытки повтора исчерпаны, то ошибка фиксируется и становится видна оператору."
  ],
  "confidence": "medium",
  "document_readiness": "needs_clarification",
  "model_needs_review": false
}
```

## Пример `FinalReview` после QC

Если исходный текст не расплывчатый и другие детерминированные условия не сработали:

```json
{
  "summary": "В брифе описана функция уведомлений, но не определены хранение данных и обработка сбоев.",
  "risks": [
    {
      "severity": "high",
      "category": "reliability",
      "description": "Для неуспешной доставки не определены повторные попытки и очередь недоставленных сообщений.",
      "evidence": "При наступлении события система отправляет пользователю уведомление."
    }
  ],
  "missing_requirements": [
    {
      "category": "data",
      "description": "Не указан срок хранения истории уведомлений."
    }
  ],
  "contradictions": [],
  "questions_to_client": [
    "Каков срок хранения истории уведомлений?",
    "Нужно ли повторять неуспешную доставку и по какой политике?"
  ],
  "acceptance_criteria": [
    "Если пользователь подписан на уведомления, когда наступает подтверждённое событие, то система доставляет ровно одно уведомление в течение 60 секунд.",
    "Если доставка завершилась ошибкой, когда попытки повтора исчерпаны, то ошибка фиксируется и становится видна оператору."
  ],
  "confidence": "medium",
  "document_readiness": "needs_clarification",
  "needs_review": false,
  "review_reason_codes": []
}
```

## Соответствие персистентности и API

| Поле `FinalReview` | SQLite | API |
| --- | --- | --- |
| весь объект | `review_json` | `review_json` |
| `confidence` | `confidence` | `confidence` |
| `document_readiness` | `readiness` | `readiness` |
| `needs_review` | `needs_review` | `needs_review` |
| `review_reason_codes` | `reason_codes_json` | `reason_codes` |

`model_needs_review` не появляется в review-колонках SQLite, JSON API или CSV-экспорте.
Связанные документы: [DATA_MODEL.md](DATA_MODEL.md),
[API_CONTRACTS.md](API_CONTRACTS.md), [ARCHITECTURE.md](ARCHITECTURE.md).

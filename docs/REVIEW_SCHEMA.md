# Review Schema

This document defines two distinct schemas:

1. **`ModelReviewDraft`** — untrusted OpenAI Structured Outputs payload, validated by Pydantic before deterministic QC.
2. **`FinalReview`** — backend-produced object stored in `reviews.review_json` and returned by the API.

The **backend**, not the LLM, writes `needs_review` and `review_reason_codes`. The model cannot propose, select, or preserve any reason code.

---

## A. ModelReviewDraft

Strict schema returned by OpenAI Structured Outputs and validated by Pydantic **before** deterministic QC.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `summary` | string | yes | Concise review summary |
| `risks` | array of Risk | yes | Identified risks; may be empty |
| `missing_requirements` | array of MissingRequirement | yes | Gaps; may be empty |
| `contradictions` | array of Contradiction | yes | Contradictions; may be empty |
| `questions_to_client` | array of string | yes | Clarifying questions; may be empty |
| `acceptance_criteria` | array of string | yes | Measurable acceptance criteria; may be empty |
| `confidence` | enum | yes | Model confidence label |
| `document_readiness` | enum | yes | Readiness assessment proposed by the model |
| `model_needs_review` | boolean | yes | Model-proposed manual-review flag |

Rules:

- `model_needs_review` is a required boolean proposed by the model;
- `ModelReviewDraft` must **not** contain `needs_review`;
- `ModelReviewDraft` must **not** contain `review_reason_codes`;
- the model cannot propose, select, or preserve any reason code;
- **additional properties are forbidden** on the top-level object and on every nested object (`Risk`, `MissingRequirement`, `Contradiction`).

`ModelReviewDraft` is never persisted as `reviews.review_json` and is never returned by the API.

### String validation

Pydantic validates every required string **after trimming whitespace**. Required strings must not be empty after trim. This applies to:

- `summary`
- `risks[].description`
- `risks[].evidence` when not `null`
- `missing_requirements[].description`
- `contradictions[].description`
- each string in `contradictions[].evidence`
- each string in `questions_to_client`
- each string in `acceptance_criteria`

A blank required string after trimming fails Pydantic validation and follows the `SCHEMA_MISMATCH` fallback path. It is not treated as a successful review.

Empty arrays remain allowed for list fields where the schema permits them.

---

## B. FinalReview

Backend-produced object stored in `reviews.review_json` and returned inside API responses (including standalone `POST /api/ai/review` and the single-review CSV export's `Полный результат JSON` cell).

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `summary` | string | yes | Copied from draft or fallback template |
| `risks` | array of Risk | yes | Copied from draft or empty in fallback |
| `missing_requirements` | array of MissingRequirement | yes | Copied from draft or empty in fallback |
| `contradictions` | array of Contradiction | yes | Copied from draft or empty in fallback |
| `questions_to_client` | array of string | yes | Copied from draft or fallback template |
| `acceptance_criteria` | array of string | yes | Copied from draft or empty in fallback |
| `confidence` | enum | yes | From draft or `"low"` in fallback |
| `document_readiness` | enum | yes | From draft or `"not_ready"` in fallback |
| `needs_review` | boolean | yes | Written **only** by the backend |
| `review_reason_codes` | array of ReasonCode | yes | Written **only** by the backend |

Rules:

- `model_needs_review` is **not** persisted or returned as part of `FinalReview`;
- `needs_review` is written only by the backend;
- `review_reason_codes` is written only by the backend;
- **additional properties remain forbidden**.

---

## Nested types

Shared by `ModelReviewDraft` and `FinalReview`. Additional properties forbidden on each nested object.

### Risk

| Field | Type | Required | Nullable |
| --- | --- | --- | --- |
| `severity` | `low` \| `medium` \| `high` | yes | no |
| `category` | Category | yes | no |
| `description` | string | yes | no |
| `evidence` | string \| null | yes | yes — `null` when no direct excerpt is available |

### MissingRequirement

| Field | Type | Required | Nullable |
| --- | --- | --- | --- |
| `category` | Category | yes | no |
| `description` | string | yes | no |

### Contradiction

| Field | Type | Required | Nullable |
| --- | --- | --- | --- |
| `description` | string | yes | no |
| `evidence` | array of string | yes | no — may be empty; non-empty excerpts preferred when available |

---

## Enumerations

### Category (risks and missing requirements)

Closed string enum. Implementations must reject unknown values at schema validation.

| Value |
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

### confidence

| Value | Meaning |
| --- | --- |
| `high` | Strong signal in the source text; limited ambiguity |
| `medium` | Partial ambiguity or incomplete detail |
| `low` | Weak, vague, or unreliable basis for conclusions |

### document_readiness

| Value | Meaning |
| --- | --- |
| `ready` | Sufficient for implementation planning with minor gaps |
| `needs_clarification` | Proceed only after answering key questions |
| `not_ready` | Material gaps or contradictions block readiness |

### review_reason_codes (catalogue order)

Backend-only closed set. Catalogue order is the required normalization order:

| Order | Code | Class | Exact condition |
| --- | --- | --- | --- |
| 1 | `LOW_CONFIDENCE` | content-derived | `confidence == "low"` on a validated `ModelReviewDraft` |
| 2 | `TOO_VAGUE_INPUT` | content-derived or optional on fallback | original input fails the exact vagueness thresholds |
| 3 | `CONTRADICTORY_INPUT` | content-derived | `len(contradictions) > 0` on a validated `ModelReviewDraft` |
| 4 | `MISSING_ACCEPTANCE_CRITERIA` | content-derived | `acceptance_criteria` is empty on a validated `ModelReviewDraft` |
| 5 | `INSUFFICIENT_QUESTIONS` | content-derived | input is vague **and** `len(questions_to_client) < 3` on a validated `ModelReviewDraft` |
| 6 | `INVALID_JSON` | failure-provenance only | response cannot be parsed as JSON |
| 7 | `SCHEMA_MISMATCH` | failure-provenance only | parsed data fails the strict Pydantic `ModelReviewDraft` schema |
| 8 | `MODEL_ERROR` | failure-provenance only | provider/API/transport/model-call failure |

`MODEL_ERROR`, `INVALID_JSON`, and `SCHEMA_MISMATCH` must **never** occur in a successfully parsed and validated model review.

---

## Exact vagueness definition

```text
normalized_text = " ".join(text.split())

too_vague =
  len(normalized_text) < 200
  OR len(normalized_text.split(" ")) < 30
```

No additional application-defined vagueness heuristics are permitted in the approved MVP.

---

## Backend construction from a validated ModelReviewDraft

For a successfully parsed and Pydantic-validated `ModelReviewDraft`:

```text
deterministic_reason_codes =
  reason codes whose documented backend conditions actually fired

final_needs_review =
  model_review_draft.model_needs_review
  OR len(deterministic_reason_codes) > 0

final_review.review_reason_codes =
  deterministic_reason_codes
```

The backend reconstructs `final_review.review_reason_codes` **exclusively** from verified conditions. It must not union, preserve, copy, filter, or otherwise use model-provided reason codes, because the model does not return them.

### Content-derived codes (successful path only)

| Code | Exact condition |
| --- | --- |
| `LOW_CONFIDENCE` | only when `confidence == "low"` |
| `TOO_VAGUE_INPUT` | only when the original input fails the exact documented thresholds |
| `CONTRADICTORY_INPUT` | only when `len(contradictions) > 0` |
| `MISSING_ACCEPTANCE_CRITERIA` | only when `acceptance_criteria` is empty |
| `INSUFFICIENT_QUESTIONS` | only when the input is vague and `len(questions_to_client) < 3` |

Content-derived codes must **not** be inferred from synthetic fallback fields.

### model_needs_review without deterministic codes

If `model_needs_review=true` but no deterministic condition fires:

```json
{
  "needs_review": true,
  "review_reason_codes": []
}
```

Do **not** add a new reason code merely to explain the model flag.

Audit for this case: `status="needs_review"`, `error=null`.

### When final_needs_review is false

If `final_needs_review=false`, `review_reason_codes` must be `[]`.

### Normalization

- Deduplicate reason codes.
- Order by the fixed catalogue order above.
- On the successful path, only content-derived codes (plus never failure-provenance codes) may appear.

`FinalReview.needs_review` is set to `final_needs_review`. Content fields are copied from the draft into `FinalReview` without exposing `model_needs_review`.

---

## Failure-only reason codes and safe fallback

Failure-provenance codes are backend-generated only:

| Failure provenance | Root technical code |
| --- | --- |
| provider/API/transport/model-call failure | `MODEL_ERROR` |
| response cannot be parsed as JSON | `INVALID_JSON` |
| parsed data fails strict Pydantic `ModelReviewDraft` schema (including blank required string after trim) | `SCHEMA_MISMATCH` |

They must never occur on a successfully parsed and validated `ModelReviewDraft`.

### Safe FinalReview fallback

```json
{
  "summary": "Automated review could not be completed reliably. Manual review is required.",
  "risks": [],
  "missing_requirements": [],
  "contradictions": [],
  "questions_to_client": [
    "Can you provide a more complete and specific requirements document?"
  ],
  "acceptance_criteria": [],
  "confidence": "low",
  "document_readiness": "not_ready",
  "needs_review": true,
  "review_reason_codes": ["MODEL_ERROR"]
}
```

| Failure mode | Root-cause codes | Optional append |
| --- | --- | --- |
| Model/API/transport failure | `["MODEL_ERROR"]` | `TOO_VAGUE_INPUT` if original input fails vagueness thresholds |
| JSON parse failure | `["INVALID_JSON"]` | `TOO_VAGUE_INPUT` if original input fails vagueness thresholds |
| Schema validation failure | `["SCHEMA_MISMATCH"]` | `TOO_VAGUE_INPUT` if original input fails vagueness thresholds |

Always:

- `needs_review=true`
- `confidence="low"`
- `document_readiness="not_ready"`
- empty `risks`, `missing_requirements`, `contradictions`, `acceptance_criteria`
- no fabricated domain-specific findings
- do not invent extra questions beyond the single safe question above
- do not add `LOW_CONFIDENCE`, `MISSING_ACCEPTANCE_CRITERIA`, `INSUFFICIENT_QUESTIONS`, or `CONTRADICTORY_INPUT` from synthetic fallback fields

### Persisted technical fallback

When a safe fallback `FinalReview` (above) is successfully persisted for a
document-backed review:

- `Review` is stored (not skipped);
- `review_json` contains the valid safe fallback `FinalReview` shown above;
- `Review.needs_review = true`;
- `Review.error` is a non-empty, sanitized string (never `null`): a fixed,
  business-facing message, never the raw exception/message/traceback/provider
  payload, and never the `LLMErrorCategory` value either — that value is recorded
  separately, only as technical metadata in `AuditRun.output_json.llm_error_category`;
- `AuditRun.status = "error"`;
- `AuditRun.error` is the same non-empty, sanitized string;
- `Document.status = "review_failed"` — **not** `reviewed`: a persisted fallback is a
  technical failure that was safely contained, not a completed automated review;
- the endpoint still returns HTTP `201`, because a usable `Review` row was in fact
  saved.

### Successful manual review (not a technical fallback)

Kept distinct from the above: a successfully parsed and validated `ModelReviewDraft`
that the backend flags for manual attention (deterministic codes and/or
`model_needs_review=true`, "model_needs_review without deterministic codes" above)
is **not** a technical failure:

- `needs_review = true`;
- `Review.error = null`;
- `AuditRun.status = "needs_review"`;
- `AuditRun.error = null`;
- `Document.status = "reviewed"`.

`needs_review=true` alone never indicates a technical failure — only `used_fallback`
(the orchestrator's own typed outcome) does. See [ARCHITECTURE.md](ARCHITECTURE.md)
and [API_CONTRACTS.md](API_CONTRACTS.md) for the full outcome matrix.

---

## Schema version literal

The approved MVP review schema version string recorded in every AI-invoking audit snapshot is:

```text
review_schema_version = "spec-review-schema-v1"
```

The companion prompt version string is:

```text
prompt_version = "spec-review-prompt-v2"
```

These are application constants stored inside audit `input_json` or `output_json`, not new database columns. A material schema change requires a new `review_schema_version` literal; previous literals must not be silently reused.

---

## Example ModelReviewDraft

```json
{
  "summary": "The brief outlines a notification feature but leaves data retention and failure handling unspecified.",
  "risks": [
    {
      "severity": "high",
      "category": "reliability",
      "description": "No retry or dead-letter behaviour is defined for failed deliveries.",
      "evidence": "Notifications are sent to users when events occur."
    }
  ],
  "missing_requirements": [
    {
      "category": "data",
      "description": "Retention period for notification history is not specified."
    }
  ],
  "contradictions": [],
  "questions_to_client": [
    "What is the retention period for notification history?",
    "Should failed deliveries be retried, and with what policy?"
  ],
  "acceptance_criteria": [
    "Если пользователь подписан и наступает триггерное событие, когда событие обработано, то пользователь получает ровно одно уведомление в течение 60 секунд в штатном режиме работы.",
    "Если доставка завершилась ошибкой, когда попытки повтора исчерпаны, то ошибка фиксируется и становится видна оператору."
  ],
  "confidence": "medium",
  "document_readiness": "needs_clarification",
  "model_needs_review": false
}
```

## Example FinalReview after QC

Assuming the original input is not vague and no content-derived condition fires:

```json
{
  "summary": "The brief outlines a notification feature but leaves data retention and failure handling unspecified.",
  "risks": [
    {
      "severity": "high",
      "category": "reliability",
      "description": "No retry or dead-letter behaviour is defined for failed deliveries.",
      "evidence": "Notifications are sent to users when events occur."
    }
  ],
  "missing_requirements": [
    {
      "category": "data",
      "description": "Retention period for notification history is not specified."
    }
  ],
  "contradictions": [],
  "questions_to_client": [
    "What is the retention period for notification history?",
    "Should failed deliveries be retried, and with what policy?"
  ],
  "acceptance_criteria": [
    "Если пользователь подписан и наступает триггерное событие, когда событие обработано, то пользователь получает ровно одно уведомление в течение 60 секунд в штатном режиме работы.",
    "Если доставка завершилась ошибкой, когда попытки повтора исчерпаны, то ошибка фиксируется и становится видна оператору."
  ],
  "confidence": "medium",
  "document_readiness": "needs_clarification",
  "needs_review": false,
  "review_reason_codes": []
}
```

Notes:

- If `model_needs_review=false` and no deterministic condition fires → `needs_review=false`, `review_reason_codes=[]`.
- If `model_needs_review=true` and no deterministic condition fires → `needs_review=true`, `review_reason_codes=[]` (no invented code).
- If `acceptance_criteria` is empty on a validated draft → backend adds `MISSING_ACCEPTANCE_CRITERIA` and `needs_review=true`.

---

## Alignment with persistence and API

| FinalReview field | SQLite column | API field |
| --- | --- | --- |
| full `FinalReview` object | `review_json` | `review_json` |
| `confidence` | `confidence` | `confidence` |
| `document_readiness` | `readiness` | `readiness` |
| `needs_review` | `needs_review` | `needs_review` |
| `review_reason_codes` | `reason_codes_json` | `reason_codes` |

`model_needs_review` is never stored in SQLite review columns and never appears in list, detail, standalone AI, or export responses.

See [DATA_MODEL.md](DATA_MODEL.md) and [API_CONTRACTS.md](API_CONTRACTS.md).

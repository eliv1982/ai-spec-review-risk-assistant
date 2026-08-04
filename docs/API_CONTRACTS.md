# API Contracts

All timestamps are canonical UTC ISO 8601 strings with a trailing `Z` (for example `2026-08-04T18:30:00Z`).
All resource identifiers are UUID strings.
Request and response bodies use JSON unless noted.

Common error envelope (unless an endpoint specifies otherwise):

```json
{
  "detail": "Human-readable error message"
}
```

Validation errors (HTTP `422`) may use FastAPI/Pydantic detail arrays.

### Validation rules (deterministic)

- Missing, invalid, blank-after-trim, or incorrectly typed request fields → HTTP `422`.
- Invalid UUID path or query values → HTTP `422`.
- HTTP `400` is not used for these cases and is not an implementation choice versus `422`.

### Pagination (all list endpoints)

| Parameter | Default | Minimum | Maximum |
| --- | --- | --- | --- |
| `limit` | `50` | `1` | `100` |
| `offset` | `0` | `0` | none |

Ordering for every list endpoint: `created_at DESC`, then `id DESC` as a deterministic tie-breaker.

Values outside the allowed ranges, or incorrectly typed pagination parameters, return HTTP `422`.

```text
total = number of records matching all active filters before limit and offset are applied
```

`total` is **not** the total unfiltered table size and **not** the number of items on the current page.

### Reason codes field naming

- SQLite column name: `reason_codes_json` (JSON text array). See [DATA_MODEL.md](DATA_MODEL.md).
- API response field name in all review payloads (create/list/detail/export and standalone AI): `reason_codes` — a native JSON array.
- The API serializes `reason_codes_json` as `reason_codes`. Clients never see the column name `reason_codes_json`.

---

## GET /api/health

**Purpose:** Liveness check for the backend process.

**Request parameters / body:** None.

**Success response:** `200`

```json
{
  "status": "ok"
}
```

**Errors:**

| Code | When |
| --- | --- |
| 500 | Unexpected server failure |

**Audit action name:** none (not audited).

**Creates domain record:** no.

---

## POST /api/documents

**Purpose:** Create a document from plain text.

**Request body:**

```json
{
  "title": "string",
  "text": "string"
}
```

| Field | Required | Rules |
| --- | --- | --- |
| `title` | yes | non-empty string after trim |
| `text` | yes | non-empty string after trim |

**Success response:** `201`

```json
{
  "id": "uuid",
  "created_at": "2026-08-04T18:30:00Z",
  "title": "string",
  "text": "string",
  "status": "created"
}
```

Document row and audit row are committed atomically. Audit: `action=document.create`, `entity_type="document"`, `entity_id=<created document id>`, `status="success"`, `error=null`.

**Errors:**

| Code | When |
| --- | --- |
| 422 | Missing, invalid, blank-after-trim, or incorrectly typed fields |
| 500 | Unexpected server failure (must not be reported as success if the required audit row cannot be stored) |

**Audit action name:** `document.create`

**Creates domain record:** yes — `documents` row. Also creates `audit_runs` row.

---

## GET /api/documents

**Purpose:** List documents with optional filters and pagination.

**Query parameters:**

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `status` | string enum | no | `created` \| `reviewed` \| `review_failed` |
| `limit` | integer | no | Default `50`; minimum `1`; maximum `100` |
| `offset` | integer | no | Default `0`; minimum `0` |

Ordering: `created_at DESC`, then `id DESC`.

`total` is the number of documents matching all active filters before `limit` and `offset` are applied.

**Success response:** `200`

```json
{
  "items": [
    {
      "id": "uuid",
      "created_at": "2026-08-04T18:30:00Z",
      "title": "string",
      "text": "string",
      "status": "created"
    }
  ],
  "total": 0,
  "limit": 50,
  "offset": 0
}
```

**Errors:**

| Code | When |
| --- | --- |
| 422 | Invalid query parameter types/values, including out-of-range `limit`/`offset` or invalid `status` |
| 500 | Unexpected server failure |

**Audit action name:** none (read-only list; not audited).

**Creates domain record:** no.

---

## GET /api/documents/{document_id}

**Purpose:** Fetch a single document by id.

**Path parameters:**

| Name | Type | Required |
| --- | --- | --- |
| `document_id` | uuid string | yes |

**Success response:** `200`

```json
{
  "id": "uuid",
  "created_at": "2026-08-04T18:30:00Z",
  "title": "string",
  "text": "string",
  "status": "created"
}
```

**Errors:**

| Code | When |
| --- | --- |
| 404 | Document not found |
| 422 | `document_id` is not a valid UUID |
| 500 | Unexpected server failure |

**Audit action name:** none (read-only; not audited).

**Creates domain record:** no.

---

## POST /api/documents/{document_id}/review

**Purpose:** Run the full review pipeline for an existing document and persist the result.

**Path parameters:**

| Name | Type | Required |
| --- | --- | --- |
| `document_id` | uuid string | yes |

**Request body:** none.

**Success response:** `201`

```json
{
  "id": "uuid",
  "created_at": "2026-08-04T18:30:00Z",
  "document_id": "uuid",
  "review_json": { },
  "confidence": "low",
  "readiness": "needs_clarification",
  "needs_review": true,
  "reason_codes": ["LOW_CONFIDENCE"],
  "error": null
}
```

`review_json` is a backend-produced **`FinalReview`** object as defined in [REVIEW_SCHEMA.md](REVIEW_SCHEMA.md). It includes backend-written `needs_review` and `review_reason_codes`. It does **not** include `model_needs_review`.

Top-level denormalized response fields:

| Response field | Source |
| --- | --- |
| `confidence` | `review_json.confidence` |
| `readiness` | `review_json.document_readiness` |
| `needs_review` | `review_json.needs_review` (final backend value) |
| `reason_codes` | `review_json.review_reason_codes` (API serialization of column `reason_codes_json`) |

`model_needs_review` is never exposed in persisted review responses, list responses, detail responses, standalone AI responses, or JSON exports.

### Persistence and status outcomes

- **Parsed `ModelReviewDraft` result or persisted safe `FinalReview` fallback:** commit review row, set document `status=reviewed`, and write audit atomically. Return `201` with the review payload. For fallbacks, review `needs_review=true`, review `error` non-null when applicable, and audit `status="error"` with a non-empty sanitized audit `error`. Successfully parsed results requiring human attention (including `model_needs_review=true` with empty deterministic codes) use audit `status="needs_review"` and audit `error=null`.
- **No usable review can be stored:** roll back the failed review transaction; in a separate recovery transaction set `document.status="review_failed"` and write the error audit row with `entity_type="document"`, `entity_id=<document id>`, `status="error"`, and a non-empty sanitized `error`. Return HTTP `500` (or the concrete failure status if the document was not found — `404`).

`review_failed` reflects the latest document-backed review attempt that failed before a usable review row was persisted. A later successful or fallback-persisted attempt may change the document back to `reviewed`.

Preferred MVP behaviour for model/JSON/schema failure is always to persist the safe fallback and return `201` when persistence succeeds. Do not surface upstream failures as HTTP `502` when a safe fallback can be returned.

### Audit for this endpoint

Every `document.review` audit snapshot records `prompt_version="spec-review-prompt-v1"`, `review_schema_version="spec-review-schema-v1"`, and the configured model name inside `input_json` or `output_json`.

| Outcome | Audit `status` | Audit `error` | `entity_type` / `entity_id` |
| --- | --- | --- | --- |
| Validated `ModelReviewDraft` → `FinalReview`, final `needs_review=false` | `success` | `null` | `review` / created review id |
| Validated `ModelReviewDraft` → `FinalReview`, final `needs_review=true` (deterministic codes and/or `model_needs_review=true`) | `needs_review` | `null` | `review` / created review id |
| Safe `FinalReview` fallback persisted | `error` | non-empty sanitized summary | `review` / created review id |
| Failure before a review exists | `error` | non-empty sanitized summary | `document` / document id |

**Errors:**

| Code | When |
| --- | --- |
| 404 | Document not found |
| 422 | Invalid `document_id` |
| 500 | Unexpected server failure, or failure to persist a usable review / required audit |

**Audit action name:** `document.review`

**Creates domain record:** yes — `reviews` row when usable; updates `documents.status`; creates `audit_runs` row.

---

## GET /api/reviews

**Purpose:** List persisted reviews with filters and pagination.

**Query parameters:**

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `document_id` | uuid string | no | Filter by parent document |
| `needs_review` | boolean | no | Filter by final `needs_review` |
| `confidence` | string enum | no | `high` \| `medium` \| `low` |
| `readiness` | string enum | no | `ready` \| `needs_clarification` \| `not_ready` |
| `limit` | integer | no | Default `50`; minimum `1`; maximum `100` |
| `offset` | integer | no | Default `0`; minimum `0` |

Ordering: `created_at DESC`, then `id DESC`.

`total` is the number of reviews matching all active filters before `limit` and `offset` are applied.

**Success response:** `200`

```json
{
  "items": [
    {
      "id": "uuid",
      "created_at": "2026-08-04T18:30:00Z",
      "document_id": "uuid",
      "review_json": { },
      "confidence": "low",
      "readiness": "not_ready",
      "needs_review": true,
      "reason_codes": [
        "LOW_CONFIDENCE",
        "TOO_VAGUE_INPUT"
      ],
      "error": null
    }
  ],
  "total": 0,
  "limit": 50,
  "offset": 0
}
```

`review_json` is always a `FinalReview`. `model_needs_review` is never present.

**Errors:**

| Code | When |
| --- | --- |
| 422 | Invalid query parameter types/values, including invalid UUID `document_id` or out-of-range pagination |
| 500 | Unexpected server failure |

**Audit action name:** none (read-only list; not audited).

**Creates domain record:** no.

---

## GET /api/reviews/{review_id}

**Purpose:** Fetch a single persisted review.

**Path parameters:**

| Name | Type | Required |
| --- | --- | --- |
| `review_id` | uuid string | yes |

**Success response:** `200` — same review object shape as list items (includes `reason_codes`; `review_json` is `FinalReview`; no `model_needs_review`).

**Errors:**

| Code | When |
| --- | --- |
| 404 | Review not found |
| 422 | Invalid `review_id` |
| 500 | Unexpected server failure |

**Audit action name:** none (read-only; not audited).

**Creates domain record:** no.

---

## GET /api/reviews/{review_id}/export

**Purpose:** Export a review as downloadable JSON.

**Path parameters:**

| Name | Type | Required |
| --- | --- | --- |
| `review_id` | uuid string | yes |

**Success response:** `200`

Content-Type: `application/json`

The audit row is written **before** the export response is returned. Audit: `action=review.export`, `entity_type="review"`, `entity_id=<review id>`. Successful export → `status="success"` and `error=null`. Export failure → `status="error"` with a non-empty sanitized `error` summary; the action must not be reported as successful without the audit row.

Exported `review.review_json` is a `FinalReview`. `model_needs_review` is never included.

```json
{
  "exported_at": "2026-08-04T18:30:00Z",
  "review": {
    "id": "uuid",
    "created_at": "2026-08-04T18:30:00Z",
    "document_id": "uuid",
    "review_json": { },
    "confidence": "low",
    "readiness": "needs_clarification",
    "needs_review": true,
    "reason_codes": ["LOW_CONFIDENCE"],
    "error": null
  },
  "document": {
    "id": "uuid",
    "created_at": "2026-08-04T18:30:00Z",
    "title": "string",
    "text": "string",
    "status": "reviewed"
  }
}
```

**Errors:**

| Code | When |
| --- | --- |
| 404 | Review not found (or linked document missing) |
| 422 | Invalid `review_id` |
| 500 | Unexpected server failure |

**Audit action name:** `review.export`

**Creates domain record:** no domain document/review row. Creates `audit_runs` row only.

---

## POST /api/ai/review

**Purpose:** Demonstrate the AI review operation on arbitrary text without creating document or review domain records.

**Request body:**

```json
{
  "title": "string",
  "text": "string"
}
```

| Field | Required | Rules |
| --- | --- | --- |
| `title` | no | optional label for audit context; may be omitted; if present and blank after trim → `422` |
| `text` | yes | non-empty string after trim |

**Success response:** `200`

```json
{
  "review_json": { },
  "confidence": "low",
  "readiness": "needs_clarification",
  "needs_review": true,
  "reason_codes": ["LOW_CONFIDENCE"],
  "error": null
}
```

Pipeline: input validation → OpenAI Structured Outputs (`ModelReviewDraft`) → Pydantic validation → deterministic QC producing `FinalReview` (or safe `FinalReview` fallback) → write audit → response.

The response body exposes a **`FinalReview`** (as `review_json` plus denormalized top-level fields), **not** the raw `ModelReviewDraft`. `model_needs_review` is never returned.

`needs_review` and `reason_codes` are the **final backend** values. On model/JSON/schema failure, return the safe `FinalReview` fallback with `needs_review=true`. Preferred MVP behaviour is `200` + safe fallback; do not use HTTP `502` when a fallback can be returned.

The audit row is written **before** returning a successful or fallback response. Both `entity_type` and `entity_id` are null. Every `ai.review` audit snapshot records these application constants inside `input_json` or `output_json` (not as database columns), together with the configured model name:

```text
prompt_version = "spec-review-prompt-v1"
review_schema_version = "spec-review-schema-v1"
```

Later prompt or schema changes require a new version literal. Previous version strings must not be silently reused after a material prompt or schema change.

| Outcome | Audit `status` | Audit `error` |
| --- | --- | --- |
| Validated `ModelReviewDraft` → `FinalReview`, final `needs_review=false` | `success` | `null` |
| Validated `ModelReviewDraft` → `FinalReview`, final `needs_review=true` | `needs_review` | `null` |
| Safe `FinalReview` fallback returned | `error` | non-empty sanitized summary |

**Errors:**

| Code | When |
| --- | --- |
| 422 | Missing, invalid, blank-after-trim, or incorrectly typed fields |
| 500 | Unexpected server failure (including inability to store the required audit row) |

**Audit action name:** `ai.review`

**Creates domain record:** **no** `documents` or `reviews` row. **Yes** — creates `audit_runs` row. `entity_type` and `entity_id` are both null.

---

## GET /api/audit-runs

**Purpose:** List audit records with filters and pagination.

**Query parameters:**

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `status` | string enum | no | `success` \| `needs_review` \| `error` |
| `action` | string | no | Exact audit action name (for example `document.review`) |
| `errors_only` | boolean | no | When `true`, return rows where `status == "error"` only |
| `limit` | integer | no | Default `50`; minimum `1`; maximum `100` |
| `offset` | integer | no | Default `0`; minimum `0` |

Ordering: `created_at DESC`, then `id DESC`.

`total` is the number of audit runs matching all active filters before `limit` and `offset` are applied.

**Success response:** `200`

```json
{
  "items": [
    {
      "id": "uuid",
      "created_at": "2026-08-04T18:30:00Z",
      "action": "document.review",
      "entity_type": "review",
      "entity_id": "uuid",
      "input_json": { },
      "output_json": { },
      "status": "needs_review",
      "error": null,
      "duration_ms": 1234
    }
  ],
  "total": 0,
  "limit": 50,
  "offset": 0
}
```

**Errors:**

| Code | When |
| --- | --- |
| 422 | Invalid query parameter types/values, including out-of-range pagination or invalid `status` |
| 500 | Unexpected server failure |

**Audit action name:** none (listing audits is not audited).

**Creates domain record:** no.

---

## GET /api/audit-runs/{audit_run_id}

**Purpose:** Fetch a single audit run.

**Path parameters:**

| Name | Type | Required |
| --- | --- | --- |
| `audit_run_id` | uuid string | yes |

**Success response:** `200` — same object shape as list items.

**Errors:**

| Code | When |
| --- | --- |
| 404 | Audit run not found |
| 422 | Invalid `audit_run_id` |
| 500 | Unexpected server failure |

**Audit action name:** none (read-only; not audited).

**Creates domain record:** no.

---

## Audit action catalogue

| Action | Endpoint | Domain records | Entity mapping |
| --- | --- | --- | --- |
| `document.create` | `POST /api/documents` | `documents` + `audit_runs` | `document` / created document id |
| `document.review` | `POST /api/documents/{document_id}/review` | `reviews` (+ status update) when usable + `audit_runs` | `review` / review id when persisted; else `document` / document id |
| `review.export` | `GET /api/reviews/{review_id}/export` | `audit_runs` only | `review` / review id |
| `ai.review` | `POST /api/ai/review` | `audit_runs` only | both entity fields null |

### Audit status meanings

| Status | Meaning |
| --- | --- |
| `success` | The action completed without a technical error and manual review is not required |
| `needs_review` | The model response was successfully parsed and validated, but the final deterministic result requires manual review |
| `error` | Model, transport, JSON parsing, schema validation, persistence, or export failure occurred, including cases where a safe fallback was returned or persisted |

Status / `error` field invariants:

- when `audit_runs.status == "error"`, `audit_runs.error` must contain a non-empty sanitized error summary;
- when `audit_runs.status` is `"success"` or `"needs_review"`, `audit_runs.error` must be `null`;
- technical failures that return or persist a safe fallback still use `status="error"` with a non-null sanitized error summary;
- successfully parsed and validated reviews requiring human attention use `status="needs_review"` and `error=null`.

`errors_only=true` means only `status == "error"`. It is not defined as `status=error OR error is non-null`, because the invariants above make that redundant and inconsistent rows must not be treated as valid data.

Health and read/list endpoints are not audited.

/**
 * Minimal runtime validation for successful API responses. Each `parse*`
 * function throws a plain `Error` (developer-facing, never rendered as-is)
 * when the payload does not satisfy the fields the UI actually depends on;
 * `request()` in `client.ts` catches that and turns it into a safe, Russian
 * `ApiError`. Deliberately not a full schema-validation library — just
 * enough to stop a malformed/unexpected successful response from crashing
 * the UI or being silently cast with `as T`.
 */
import {
  AUDIT_STATUS_VALUES,
  DOCUMENT_STATUS_VALUES,
  REVIEW_CONFIDENCE_VALUES,
  REVIEW_READINESS_VALUES,
  RISK_CATEGORY_VALUES,
  RISK_SEVERITY_VALUES,
} from "../types/api";
import type {
  AuditRunResponse,
  Contradiction,
  DocumentResponse,
  FinalReview,
  MissingRequirement,
  PaginatedResponse,
  ReviewResponse,
  Risk,
} from "../types/api";

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireString(value: unknown, field: string): string {
  if (typeof value !== "string") throw new Error(`${field} must be a string`);
  return value;
}

/**
 * Strictly validates a closed backend enum: the value must be a string that
 * is an exact member of `allowedValues` (the same array `types/api.ts`
 * derives the TypeScript union from). No `as T` escape hatch is available
 * without first passing this runtime membership check, so an unrecognized
 * value (e.g. a future backend enum member the frontend doesn't know about
 * yet, or a malformed/adversarial response) is rejected rather than
 * silently accepted.
 */
function requireEnum<T extends string>(value: unknown, allowedValues: readonly T[], field: string): T {
  if (typeof value === "string" && (allowedValues as readonly string[]).includes(value)) {
    // Safe: membership in `allowedValues` was just verified above, so this
    // narrows exactly to `T`, not an unchecked escape hatch.
    return value as T;
  }
  throw new Error(
    `${field} must be one of [${allowedValues.join(", ")}], got ${JSON.stringify(value)}`,
  );
}

function requireBoolean(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${field} must be a boolean`);
  return value;
}

function requireStringArray(value: unknown, field: string): string[] {
  if (!Array.isArray(value) || !value.every((item) => typeof item === "string")) {
    throw new Error(`${field} must be an array of strings`);
  }
  return value;
}

/** `total`/`offset` (docs/API_CONTRACTS.md, "Pagination"): a finite integer
 * `>= 0`. Rejects negative values, fractional values, `NaN`, `Infinity`,
 * strings, and `null` — anything other than an actual non-negative integer. */
function requireNonNegativeInteger(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new Error(`${field} must be a non-negative integer, got ${JSON.stringify(value)}`);
  }
  return value;
}

/** `limit` (docs/API_CONTRACTS.md, "Pagination"): a finite integer `>= 1`.
 * `Number.isInteger` already excludes `NaN`/`Infinity`/fractional values. */
function requirePositiveInteger(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 1) {
    throw new Error(`${field} must be a positive integer (>= 1), got ${JSON.stringify(value)}`);
  }
  return value;
}

function requireNullableString(value: unknown, field: string): string | null {
  if (value !== null && typeof value !== "string") throw new Error(`${field} must be a string or null`);
  return value;
}

/** Accepts `null` or a plain JSON object (never an array/primitive) — the
 * shape `audit_runs.input_json`/`output_json` always take (docs/DATA_MODEL.md). */
function requireJsonObjectOrNull(value: unknown, field: string): Record<string, unknown> | null {
  if (value === null) return null;
  if (!isRecord(value)) throw new Error(`${field} must be an object or null`);
  return value;
}

export function parseDocumentResponse(data: unknown): DocumentResponse {
  if (!isRecord(data)) throw new Error("DocumentResponse: expected an object");
  return {
    id: requireString(data.id, "DocumentResponse.id"),
    created_at: requireString(data.created_at, "DocumentResponse.created_at"),
    title: requireString(data.title, "DocumentResponse.title"),
    text: requireString(data.text, "DocumentResponse.text"),
    status: requireEnum(data.status, DOCUMENT_STATUS_VALUES, "DocumentResponse.status"),
  };
}

function parseRisk(value: unknown, index: number): Risk {
  if (!isRecord(value)) throw new Error(`FinalReview.risks[${index}]: expected an object`);
  const evidence = value.evidence;
  if (evidence !== null && typeof evidence !== "string") {
    throw new Error(`FinalReview.risks[${index}].evidence must be a string or null`);
  }
  return {
    severity: requireEnum(value.severity, RISK_SEVERITY_VALUES, `FinalReview.risks[${index}].severity`),
    category: requireEnum(value.category, RISK_CATEGORY_VALUES, `FinalReview.risks[${index}].category`),
    description: requireString(value.description, `FinalReview.risks[${index}].description`),
    evidence,
  };
}

function parseMissingRequirement(value: unknown, index: number): MissingRequirement {
  if (!isRecord(value)) throw new Error(`FinalReview.missing_requirements[${index}]: expected an object`);
  return {
    category: requireEnum(
      value.category,
      RISK_CATEGORY_VALUES,
      `FinalReview.missing_requirements[${index}].category`,
    ),
    description: requireString(
      value.description,
      `FinalReview.missing_requirements[${index}].description`,
    ),
  };
}

function parseContradiction(value: unknown, index: number): Contradiction {
  if (!isRecord(value)) throw new Error(`FinalReview.contradictions[${index}]: expected an object`);
  return {
    description: requireString(value.description, `FinalReview.contradictions[${index}].description`),
    evidence: requireStringArray(value.evidence, `FinalReview.contradictions[${index}].evidence`),
  };
}

export function parseFinalReview(data: unknown): FinalReview {
  if (!isRecord(data)) throw new Error("FinalReview: expected an object");
  if (!Array.isArray(data.risks)) throw new Error("FinalReview.risks must be an array");
  if (!Array.isArray(data.missing_requirements)) {
    throw new Error("FinalReview.missing_requirements must be an array");
  }
  if (!Array.isArray(data.contradictions)) throw new Error("FinalReview.contradictions must be an array");

  return {
    summary: requireString(data.summary, "FinalReview.summary"),
    risks: data.risks.map(parseRisk),
    missing_requirements: data.missing_requirements.map(parseMissingRequirement),
    contradictions: data.contradictions.map(parseContradiction),
    questions_to_client: requireStringArray(data.questions_to_client, "FinalReview.questions_to_client"),
    acceptance_criteria: requireStringArray(data.acceptance_criteria, "FinalReview.acceptance_criteria"),
    confidence: requireEnum(data.confidence, REVIEW_CONFIDENCE_VALUES, "FinalReview.confidence"),
    document_readiness: requireEnum(
      data.document_readiness,
      REVIEW_READINESS_VALUES,
      "FinalReview.document_readiness",
    ),
    needs_review: requireBoolean(data.needs_review, "FinalReview.needs_review"),
    review_reason_codes: requireStringArray(data.review_reason_codes, "FinalReview.review_reason_codes"),
  };
}

/**
 * Compares two string arrays for exact equality, including order — order
 * matters for `reason_codes` (`LOW_CONFIDENCE`, when present, must sort
 * first per the backend's catalogue order, docs/REVIEW_SCHEMA.md).
 */
function stringArraysMatchInOrder(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

export function parseReviewResponse(data: unknown): ReviewResponse {
  if (!isRecord(data)) throw new Error("ReviewResponse: expected an object");
  const error = data.error;
  if (error !== null && typeof error !== "string") {
    throw new Error("ReviewResponse.error must be a string or null");
  }

  const reviewJson = parseFinalReview(data.review_json);
  const confidence = requireEnum(data.confidence, REVIEW_CONFIDENCE_VALUES, "ReviewResponse.confidence");
  const readiness = requireEnum(data.readiness, REVIEW_READINESS_VALUES, "ReviewResponse.readiness");
  const needsReview = requireBoolean(data.needs_review, "ReviewResponse.needs_review");
  const reasonCodes = requireStringArray(data.reason_codes, "ReviewResponse.reason_codes");

  // The UI renders the top-level denormalized fields as the source of
  // truth (docs/DATA_MODEL.md, "Denormalization rules") and never
  // reconciles them against `review_json` itself — so a response where they
  // disagree is not a "pick one" situation, it is a malformed response the
  // whole object must be rejected for, never silently patched.
  if (needsReview !== reviewJson.needs_review) {
    throw new Error(
      `ReviewResponse.needs_review (${needsReview}) does not match review_json.needs_review (${reviewJson.needs_review})`,
    );
  }
  if (confidence !== reviewJson.confidence) {
    throw new Error(
      `ReviewResponse.confidence (${confidence}) does not match review_json.confidence (${reviewJson.confidence})`,
    );
  }
  if (readiness !== reviewJson.document_readiness) {
    throw new Error(
      `ReviewResponse.readiness (${readiness}) does not match review_json.document_readiness (${reviewJson.document_readiness})`,
    );
  }
  if (!stringArraysMatchInOrder(reasonCodes, reviewJson.review_reason_codes)) {
    throw new Error(
      "ReviewResponse.reason_codes does not match review_json.review_reason_codes " +
        `(value/order): [${reasonCodes.join(", ")}] vs [${reviewJson.review_reason_codes.join(", ")}]`,
    );
  }

  return {
    id: requireString(data.id, "ReviewResponse.id"),
    created_at: requireString(data.created_at, "ReviewResponse.created_at"),
    document_id: requireString(data.document_id, "ReviewResponse.document_id"),
    review_json: reviewJson,
    confidence,
    readiness,
    needs_review: needsReview,
    reason_codes: reasonCodes,
    error,
  };
}

export function parseAuditRunResponse(data: unknown): AuditRunResponse {
  if (!isRecord(data)) throw new Error("AuditRunResponse: expected an object");

  const status = requireEnum(data.status, AUDIT_STATUS_VALUES, "AuditRunResponse.status");
  const error = requireNullableString(data.error, "AuditRunResponse.error");

  // Project-wide audit invariant (docs/DATA_MODEL.md, "AuditStatus";
  // backend/app/services/audit_service.py::validate_audit_invariant):
  //   status == "error"                     -> error is a non-empty string
  //   status in ("success", "needs_review") -> error is null
  // `needs_review` is a successfully completed operation that requires
  // human attention, never a technical failure — it must never be able to
  // carry an error message any more than "success" can.
  if (status === "error") {
    if (error === null || error.trim() === "") {
      throw new Error('AuditRunResponse: status="error" requires a non-empty error message');
    }
  } else if (error !== null) {
    throw new Error(`AuditRunResponse: status="${status}" requires error to be null, got ${JSON.stringify(error)}`);
  }

  return {
    id: requireString(data.id, "AuditRunResponse.id"),
    created_at: requireString(data.created_at, "AuditRunResponse.created_at"),
    action: requireString(data.action, "AuditRunResponse.action"),
    entity_type: requireNullableString(data.entity_type, "AuditRunResponse.entity_type"),
    entity_id: requireNullableString(data.entity_id, "AuditRunResponse.entity_id"),
    input_json: requireJsonObjectOrNull(data.input_json, "AuditRunResponse.input_json"),
    output_json: requireJsonObjectOrNull(data.output_json, "AuditRunResponse.output_json"),
    status,
    error,
    // Not nullable per the backend schema (backend/app/schemas/audit.py::AuditRunResponse.duration_ms: int).
    duration_ms: requireNonNegativeInteger(data.duration_ms, "AuditRunResponse.duration_ms"),
  };
}

/**
 * Validates the shared `{ items, total, limit, offset }` list envelope
 * (docs/API_CONTRACTS.md, "Pagination (all list endpoints)"). `parseItem`
 * validates each element the same strict way a single-resource endpoint
 * would, so a malformed row can never slip through inside a valid envelope.
 */
export function parsePaginatedResponse<T>(
  data: unknown,
  parseItem: (item: unknown) => T,
  field: string,
): PaginatedResponse<T> {
  if (!isRecord(data)) throw new Error(`${field}: expected an object`);
  if (!Array.isArray(data.items)) throw new Error(`${field}.items must be an array`);
  return {
    items: data.items.map(parseItem),
    total: requireNonNegativeInteger(data.total, `${field}.total`),
    limit: requirePositiveInteger(data.limit, `${field}.limit`),
    offset: requireNonNegativeInteger(data.offset, `${field}.offset`),
  };
}

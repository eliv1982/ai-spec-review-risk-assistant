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
  DOCUMENT_STATUS_VALUES,
  REVIEW_CONFIDENCE_VALUES,
  REVIEW_READINESS_VALUES,
  RISK_CATEGORY_VALUES,
  RISK_SEVERITY_VALUES,
} from "../types/api";
import type {
  Contradiction,
  DocumentResponse,
  FinalReview,
  MissingRequirement,
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

export function parseReviewResponse(data: unknown): ReviewResponse {
  if (!isRecord(data)) throw new Error("ReviewResponse: expected an object");
  const error = data.error;
  if (error !== null && typeof error !== "string") {
    throw new Error("ReviewResponse.error must be a string or null");
  }
  return {
    id: requireString(data.id, "ReviewResponse.id"),
    created_at: requireString(data.created_at, "ReviewResponse.created_at"),
    document_id: requireString(data.document_id, "ReviewResponse.document_id"),
    review_json: parseFinalReview(data.review_json),
    confidence: requireEnum(data.confidence, REVIEW_CONFIDENCE_VALUES, "ReviewResponse.confidence"),
    readiness: requireEnum(data.readiness, REVIEW_READINESS_VALUES, "ReviewResponse.readiness"),
    needs_review: requireBoolean(data.needs_review, "ReviewResponse.needs_review"),
    reason_codes: requireStringArray(data.reason_codes, "ReviewResponse.reason_codes"),
    error,
  };
}

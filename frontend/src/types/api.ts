/**
 * Transport types mirroring the backend Pydantic schemas exactly
 * (see backend/app/schemas/document.py, backend/app/schemas/review.py,
 * backend/app/enums.py, docs/API_CONTRACTS.md, docs/REVIEW_SCHEMA.md).
 * Field names are kept identical to the API response bodies.
 *
 * Closed enums are declared as a `readonly [...] as const` value array first,
 * with the TypeScript union type *derived* from that array (`(typeof X)[number]`).
 * This keeps the compile-time type and the runtime-checkable value list
 * (used by `api/validators.ts`'s `requireEnum`) permanently in sync by
 * construction — there is only one place to update when a backend enum
 * changes, not two lists that can silently drift apart.
 */

export const DOCUMENT_STATUS_VALUES = ["created", "reviewed", "review_failed"] as const;
export type DocumentStatus = (typeof DOCUMENT_STATUS_VALUES)[number];

export const REVIEW_CONFIDENCE_VALUES = ["high", "medium", "low"] as const;
export type ReviewConfidence = (typeof REVIEW_CONFIDENCE_VALUES)[number];

export const REVIEW_READINESS_VALUES = ["ready", "needs_clarification", "not_ready"] as const;
export type ReviewReadiness = (typeof REVIEW_READINESS_VALUES)[number];

export const RISK_SEVERITY_VALUES = ["low", "medium", "high"] as const;
export type RiskSeverity = (typeof RISK_SEVERITY_VALUES)[number];

export const RISK_CATEGORY_VALUES = [
  "scope",
  "functionality",
  "data",
  "integration",
  "security",
  "privacy",
  "performance",
  "reliability",
  "usability",
  "operations",
  "acceptance",
  "timeline",
  "dependency",
  "compliance",
  "other",
] as const;
export type RiskCategory = (typeof RISK_CATEGORY_VALUES)[number];

/**
 * Backend-only closed set (docs/REVIEW_SCHEMA.md). Kept as `string` (not a
 * union) here so the UI can safely render a reason code the frontend does
 * not yet know about instead of failing type-narrowing at runtime.
 */
export type ReviewReasonCode = string;

export interface DocumentCreateRequest {
  title: string;
  text: string;
}

export interface DocumentResponse {
  id: string;
  created_at: string;
  title: string;
  text: string;
  status: DocumentStatus;
}

export interface Risk {
  severity: RiskSeverity;
  category: RiskCategory;
  description: string;
  evidence: string | null;
}

export interface MissingRequirement {
  category: RiskCategory;
  description: string;
}

export interface Contradiction {
  description: string;
  evidence: string[];
}

/** Backend-produced object stored in `reviews.review_json` (docs/REVIEW_SCHEMA.md, section B). */
export interface FinalReview {
  summary: string;
  risks: Risk[];
  missing_requirements: MissingRequirement[];
  contradictions: Contradiction[];
  questions_to_client: string[];
  acceptance_criteria: string[];
  confidence: ReviewConfidence;
  document_readiness: ReviewReadiness;
  needs_review: boolean;
  review_reason_codes: ReviewReasonCode[];
}

export interface ReviewResponse {
  id: string;
  created_at: string;
  document_id: string;
  review_json: FinalReview;
  confidence: ReviewConfidence;
  readiness: ReviewReadiness;
  needs_review: boolean;
  reason_codes: ReviewReasonCode[];
  error: string | null;
}

/**
 * FastAPI/Pydantic 422 validation error item shape. Represents the
 * *well-formed* shape after parsing — the raw JSON array element is
 * `unknown` and must never be trusted to have this shape without a runtime
 * check (see `parseValidationItem` in `api/client.ts`), since a malformed or
 * future-shaped backend/proxy error body may omit `loc`/`type` entirely.
 */
export interface ValidationErrorDetail {
  loc: Array<string | number>;
  msg: string;
  type: string;
}

/** Common error envelope (docs/API_CONTRACTS.md). `detail` for a 422 is an
 * array of untrusted `unknown` items, not `ValidationErrorDetail[]` — each
 * item's shape is verified at parse time, never assumed. */
export interface ApiErrorBody {
  detail?: string | unknown[];
}

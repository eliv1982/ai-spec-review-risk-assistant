import { request, requestCsvExport, type CsvExportResult } from "./client";
import { parsePaginatedResponse, parseReviewResponse } from "./validators";
import type { PaginatedResponse, ReviewConfidence, ReviewReadiness, ReviewResponse } from "../types/api";

/** POST /api/documents/{document_id}/review (docs/API_CONTRACTS.md). */
export function runDocumentReview(documentId: string, signal?: AbortSignal): Promise<ReviewResponse> {
  return request<ReviewResponse>(
    `/documents/${encodeURIComponent(documentId)}/review`,
    { method: "POST", signal },
    parseReviewResponse,
  );
}

/** GET /api/reviews/{review_id} (docs/API_CONTRACTS.md). */
export function getReview(reviewId: string, signal?: AbortSignal): Promise<ReviewResponse> {
  return request<ReviewResponse>(
    `/reviews/${encodeURIComponent(reviewId)}`,
    { method: "GET", signal },
    parseReviewResponse,
  );
}

export interface ListReviewsParams {
  /** Trimmed non-empty UUID string, or omitted for no filter. */
  documentId?: string;
  needsReview?: boolean;
  limit: number;
  offset: number;
}

/** GET /api/reviews (docs/API_CONTRACTS.md). Ordering is always
 * `created_at DESC, id DESC` — the backend, not this client, decides it. */
export function listReviews(
  params: ListReviewsParams,
  signal?: AbortSignal,
): Promise<PaginatedResponse<ReviewResponse>> {
  const query = new URLSearchParams();
  if (params.documentId) query.set("document_id", params.documentId);
  if (params.needsReview !== undefined) query.set("needs_review", String(params.needsReview));
  query.set("limit", String(params.limit));
  query.set("offset", String(params.offset));

  return request<PaginatedResponse<ReviewResponse>>(
    `/reviews?${query.toString()}`,
    { method: "GET", signal },
    (data) => parsePaginatedResponse(data, parseReviewResponse, "ReviewsList"),
  );
}

export interface ExportReviewsCsvParams {
  /** Trimmed non-empty UUID string, or omitted for no filter. */
  documentId?: string;
  needsReview?: boolean;
  confidence?: ReviewConfidence;
  readiness?: ReviewReadiness;
}

/** GET /api/reviews/export (docs/API_CONTRACTS.md). Same filters as
 * `listReviews`, but never paginated (no `limit`/`offset`) — exports every
 * matching row as CSV. */
export function exportReviewsCsv(
  params: ExportReviewsCsvParams,
  signal?: AbortSignal,
): Promise<CsvExportResult> {
  const query = new URLSearchParams();
  if (params.documentId) query.set("document_id", params.documentId);
  if (params.needsReview !== undefined) query.set("needs_review", String(params.needsReview));
  if (params.confidence) query.set("confidence", params.confidence);
  if (params.readiness) query.set("readiness", params.readiness);
  const qs = query.toString();

  return requestCsvExport(`/reviews/export${qs ? `?${qs}` : ""}`, "reviews-export.csv", signal);
}

/** GET /api/reviews/{review_id}/export (docs/API_CONTRACTS.md). */
export function exportReviewCsv(reviewId: string, signal?: AbortSignal): Promise<CsvExportResult> {
  return requestCsvExport(
    `/reviews/${encodeURIComponent(reviewId)}/export`,
    `review-${reviewId}.csv`,
    signal,
  );
}

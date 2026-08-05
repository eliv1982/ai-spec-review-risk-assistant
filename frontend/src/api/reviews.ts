import { request } from "./client";
import { parseReviewResponse } from "./validators";
import type { ReviewResponse } from "../types/api";

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

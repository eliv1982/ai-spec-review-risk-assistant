import { request } from "./client";
import { parseDocumentResponse } from "./validators";
import type { DocumentCreateRequest, DocumentResponse } from "../types/api";

/** POST /api/documents (docs/API_CONTRACTS.md). */
export function createDocument(
  payload: DocumentCreateRequest,
  signal?: AbortSignal,
): Promise<DocumentResponse> {
  return request<DocumentResponse>(
    "/documents",
    { method: "POST", body: JSON.stringify(payload), signal },
    parseDocumentResponse,
  );
}

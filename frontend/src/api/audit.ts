import { request } from "./client";
import { parseAuditRunResponse, parsePaginatedResponse } from "./validators";
import type { AuditRunResponse, AuditStatus, PaginatedResponse } from "../types/api";

export interface ListAuditRunsParams {
  status?: AuditStatus;
  errorsOnly?: boolean;
  limit: number;
  offset: number;
}

/** GET /api/audit-runs (docs/API_CONTRACTS.md). Read-only: never creates an
 * audit_runs row. Ordering is always `created_at DESC, id DESC`. */
export function listAuditRuns(
  params: ListAuditRunsParams,
  signal?: AbortSignal,
): Promise<PaginatedResponse<AuditRunResponse>> {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.errorsOnly) query.set("errors_only", "true");
  query.set("limit", String(params.limit));
  query.set("offset", String(params.offset));

  return request<PaginatedResponse<AuditRunResponse>>(
    `/audit-runs?${query.toString()}`,
    { method: "GET", signal },
    (data) => parsePaginatedResponse(data, parseAuditRunResponse, "AuditRunsList"),
  );
}

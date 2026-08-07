import { useEffect, useRef, useState } from "react";
import { exportAuditRunsCsv, listAuditRuns } from "../api/audit";
import { ApiError, isAbortError } from "../api/client";
import { downloadBlob } from "../utils/download";
import type { AuditRunResponse, AuditStatus, PaginatedResponse } from "../types/api";
import { ErrorBanner } from "../components/ErrorBanner";
import { LoadingIndicator } from "../components/LoadingIndicator";
import { Pagination } from "../components/Pagination";
import { JsonBlock } from "../components/JsonBlock";
import { auditStatusBadgeClass, labelAuditAction, labelAuditStatus, labelEntityType } from "../utils/labels";
import { formatDateTime, formatDuration } from "../utils/formatting";
import { computeCorrectedOffset } from "../utils/pagination";

const PAGE_SIZE = 20;

/** `error` reuses `errors_only=true` (docs/API_CONTRACTS.md) instead of
 * `status=error` — functionally identical for this closed status enum, but
 * exercises the dedicated `errors_only` query parameter. */
type StatusFilter = "all" | "success" | "needs_review" | "error";

type ListState =
  | { status: "loading" }
  | { status: "error"; error: ApiError }
  | { status: "loaded"; data: PaginatedResponse<AuditRunResponse> };

type ExportState = { status: "idle" } | { status: "pending" } | { status: "error"; error: ApiError };

function extractVersionMeta(record: Record<string, unknown> | null): {
  promptVersion?: string;
  schemaVersion?: string;
} {
  if (!record) return {};
  return {
    promptVersion: typeof record.prompt_version === "string" ? record.prompt_version : undefined,
    schemaVersion:
      typeof record.review_schema_version === "string" ? record.review_schema_version : undefined,
  };
}

export function AuditJournalPage() {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [offset, setOffset] = useState(0);
  const [reloadToken, setReloadToken] = useState(0);

  const [state, setState] = useState<ListState>({ status: "loading" });
  const [exportState, setExportState] = useState<ExportState>({ status: "idle" });
  // Guards the async export handler (a button click, not an effect) against
  // triggering a download or updating state after this component has
  // unmounted.
  const isMountedRef = useRef(true);
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();

    const params = {
      status: (statusFilter === "success" || statusFilter === "needs_review"
        ? statusFilter
        : undefined) as AuditStatus | undefined,
      errorsOnly: statusFilter === "error",
      limit: PAGE_SIZE,
      offset,
    };

    setState({ status: "loading" });
    listAuditRuns(params, controller.signal)
      .then((data) => {
        if (!active) return;

        // See ReviewsDashboardPage: fall back to the nearest valid page
        // instead of committing a dead-end empty state for an offset that
        // no longer fits within the current (possibly filtered) `total`.
        const corrected = computeCorrectedOffset({
          itemCount: data.items.length,
          offset: data.offset,
          total: data.total,
          pageSize: PAGE_SIZE,
        });
        if (corrected !== null) {
          setOffset(corrected);
          return;
        }

        setState({ status: "loaded", data });
      })
      .catch((err) => {
        if (!active) return;
        if (isAbortError(err)) return;
        const apiError =
          err instanceof ApiError
            ? err
            : new ApiError({ kind: "network", message: "Не удалось загрузить журнал аудита." });
        setState({ status: "error", error: apiError });
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [statusFilter, offset, reloadToken]);

  function handleStatusChange(value: StatusFilter) {
    setStatusFilter(value);
    setOffset(0);
  }

  function handleResetFilters() {
    setStatusFilter("all");
    setOffset(0);
  }

  function handlePrev() {
    setOffset((current) => Math.max(0, current - PAGE_SIZE));
  }

  function handleNext() {
    setOffset((current) => current + PAGE_SIZE);
  }

  function handleRetry() {
    setReloadToken((token) => token + 1);
  }

  async function handleExportCsv() {
    if (exportState.status === "pending") return;
    setExportState({ status: "pending" });
    try {
      const { blob, filename } = await exportAuditRunsCsv({
        status: (statusFilter === "success" || statusFilter === "needs_review"
          ? statusFilter
          : undefined) as AuditStatus | undefined,
        errorsOnly: statusFilter === "error",
      });
      if (!isMountedRef.current) return;
      downloadBlob(blob, filename);
      setExportState({ status: "idle" });
    } catch (err) {
      if (!isMountedRef.current) return;
      const apiError =
        err instanceof ApiError
          ? err
          : new ApiError({ kind: "network", message: "Не удалось сформировать CSV-файл." });
      setExportState({ status: "error", error: apiError });
    }
  }

  return (
    <main className="page">
      <div className="container-wide container-audit">
        <h1>Журнал аудита</h1>
        <p className="lead">
          История операций сервиса: создание документов, проверки и технические ошибки.
        </p>

        <div className="card filters-form">
          <div className="filters-field">
            <label htmlFor="audit-status-filter">Статус</label>
            <select
              id="audit-status-filter"
              name="audit-status-filter"
              value={statusFilter}
              onChange={(event) => handleStatusChange(event.target.value as StatusFilter)}
            >
              <option value="all">Все записи</option>
              <option value="success">Успешно</option>
              <option value="needs_review">Нужна экспертная проверка</option>
              <option value="error">Только ошибки</option>
            </select>
          </div>

          <div className="form-actions">
            <button type="button" className="button button-secondary" onClick={handleResetFilters}>
              Сбросить фильтры
            </button>
          </div>
        </div>

        <div className="form-actions">
          <button
            type="button"
            className="button button-secondary"
            onClick={handleExportCsv}
            disabled={exportState.status === "pending"}
          >
            {exportState.status === "pending" ? "Формируется CSV…" : "Скачать CSV"}
          </button>
        </div>

        {exportState.status === "error" && (
          <ErrorBanner title="Не удалось сформировать CSV-файл" message={exportState.error.message} />
        )}

        {state.status === "loading" && <LoadingIndicator message="Загружаем журнал аудита…" />}

        {state.status === "error" && (
          <>
            <ErrorBanner title="Не удалось загрузить журнал аудита" message={state.error.message} />
            <div className="form-actions">
              <button type="button" className="button button-secondary" onClick={handleRetry}>
                Повторить попытку
              </button>
            </div>
          </>
        )}

        {state.status === "loaded" && state.data.items.length === 0 && (
          <p className="empty-state">По заданному фильтру записи аудита не найдены.</p>
        )}

        {state.status === "loaded" && state.data.items.length > 0 && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Дата и время</th>
                  <th scope="col">Операция</th>
                  <th scope="col">Статус</th>
                  <th scope="col">Связанный объект</th>
                  <th scope="col">Длительность</th>
                  <th scope="col">Ошибка</th>
                  <th scope="col">Детали</th>
                </tr>
              </thead>
              <tbody>
                {state.data.items.map((run) => {
                  const inputMeta = extractVersionMeta(run.input_json);
                  const outputMeta = extractVersionMeta(run.output_json);
                  const promptVersion = inputMeta.promptVersion ?? outputMeta.promptVersion;
                  const schemaVersion = inputMeta.schemaVersion ?? outputMeta.schemaVersion;

                  return (
                    <tr key={run.id}>
                      <td>{formatDateTime(run.created_at)}</td>
                      <td>
                        {labelAuditAction(run.action)}
                        {(promptVersion || schemaVersion) && (
                          <div className="row-note">
                            {promptVersion && (
                              <>
                                prompt_version: <code>{promptVersion}</code>
                              </>
                            )}
                            {promptVersion && schemaVersion && " · "}
                            {schemaVersion && (
                              <>
                                review_schema_version: <code>{schemaVersion}</code>
                              </>
                            )}
                          </div>
                        )}
                      </td>
                      <td>
                        <span className={`badge ${auditStatusBadgeClass(run.status)}`}>
                          {labelAuditStatus(run.status)}
                        </span>
                      </td>
                      <td>
                        {run.entity_type ? (
                          <>
                            {labelEntityType(run.entity_type)}
                            <br />
                            <code className="id-cell">{run.entity_id ?? "—"}</code>
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>{formatDuration(run.duration_ms)}</td>
                      <td className="long-text">{run.error ?? "—"}</td>
                      <td>
                        <JsonBlock title="Входные данные" value={run.input_json} />
                        <JsonBlock title="Результат" value={run.output_json} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Rendered whenever a page has loaded, independent of the current
            page's item count — see ReviewsDashboardPage for why gating
            Pagination on items.length would strand users on an
            out-of-range empty page with no way back. */}
        {state.status === "loaded" && (
          <Pagination
            limit={state.data.limit}
            offset={state.data.offset}
            itemCount={state.data.items.length}
            total={state.data.total}
            onPrev={handlePrev}
            onNext={handleNext}
          />
        )}
      </div>
    </main>
  );
}

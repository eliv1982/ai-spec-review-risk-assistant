import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { exportReviewsCsv, listReviews } from "../api/reviews";
import { ApiError, isAbortError } from "../api/client";
import { downloadBlob } from "../utils/download";
import type { PaginatedResponse, ReviewResponse } from "../types/api";
import { ErrorBanner } from "../components/ErrorBanner";
import { LoadingIndicator } from "../components/LoadingIndicator";
import { Pagination } from "../components/Pagination";
import { labelConfidence, labelNeedsReview, labelReadiness, labelReasonCode } from "../utils/labels";
import { formatDateTime } from "../utils/formatting";
import { computeCorrectedOffset } from "../utils/pagination";

const PAGE_SIZE = 20;

type NeedsReviewFilter = "all" | "true" | "false";

type ListState =
  | { status: "loading" }
  | { status: "error"; error: ApiError }
  | { status: "loaded"; data: PaginatedResponse<ReviewResponse> };

type ExportState = { status: "idle" } | { status: "pending" } | { status: "error"; error: ApiError };

export function ReviewsDashboardPage() {
  const [documentIdInput, setDocumentIdInput] = useState("");
  const [needsReviewInput, setNeedsReviewInput] = useState<NeedsReviewFilter>("all");

  const [appliedDocumentId, setAppliedDocumentId] = useState<string | undefined>(undefined);
  const [appliedNeedsReview, setAppliedNeedsReview] = useState<boolean | undefined>(undefined);
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

    setState({ status: "loading" });
    listReviews(
      { documentId: appliedDocumentId, needsReview: appliedNeedsReview, limit: PAGE_SIZE, offset },
      controller.signal,
    )
      .then((data) => {
        if (!active) return;

        // The page we just requested came back empty because `total`
        // shrank (e.g. a filter narrowed results, or rows were deleted
        // elsewhere) since `offset` was last valid: fall back to the
        // nearest valid page instead of committing a dead-end empty state
        // the user could not navigate back from.
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
            : new ApiError({ kind: "network", message: "Не удалось загрузить список проверок." });
        setState({ status: "error", error: apiError });
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [appliedDocumentId, appliedNeedsReview, offset, reloadToken]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = documentIdInput.trim();
    setAppliedDocumentId(trimmed || undefined);
    setAppliedNeedsReview(needsReviewInput === "all" ? undefined : needsReviewInput === "true");
    setOffset(0);
  }

  function handleResetFilters() {
    setDocumentIdInput("");
    setNeedsReviewInput("all");
    setAppliedDocumentId(undefined);
    setAppliedNeedsReview(undefined);
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
      const { blob, filename } = await exportReviewsCsv({
        documentId: appliedDocumentId,
        needsReview: appliedNeedsReview,
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
      <div className="container-wide">
        <h1>История проверок</h1>
        <p className="lead">Сохранённые результаты проверок документов.</p>

        <form className="card filters-form" onSubmit={handleSubmit}>
          <div className="filters-field">
            <label htmlFor="document-id-filter">Идентификатор документа</label>
            <input
              id="document-id-filter"
              name="document-id-filter"
              type="text"
              value={documentIdInput}
              onChange={(event) => setDocumentIdInput(event.target.value)}
              placeholder="UUID документа"
            />
          </div>

          <div className="filters-field">
            <label htmlFor="needs-review-filter">Экспертная проверка</label>
            <select
              id="needs-review-filter"
              name="needs-review-filter"
              value={needsReviewInput}
              onChange={(event) => setNeedsReviewInput(event.target.value as NeedsReviewFilter)}
            >
              <option value="all">Все</option>
              <option value="true">{labelNeedsReview(true)}</option>
              <option value="false">{labelNeedsReview(false)}</option>
            </select>
          </div>

          <div className="form-actions">
            <button type="submit" className="button button-primary">
              Применить
            </button>
            <button type="button" className="button button-secondary" onClick={handleResetFilters}>
              Сбросить фильтры
            </button>
          </div>
        </form>

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

        {state.status === "loading" && <LoadingIndicator message="Загружаем список проверок…" />}

        {state.status === "error" && (
          <>
            <ErrorBanner title="Не удалось загрузить список проверок" message={state.error.message} />
            <div className="form-actions">
              <button type="button" className="button button-secondary" onClick={handleRetry}>
                Повторить попытку
              </button>
            </div>
          </>
        )}

        {state.status === "loaded" && state.data.items.length === 0 && (
          <p className="empty-state">По заданным фильтрам проверки не найдены.</p>
        )}

        {state.status === "loaded" && state.data.items.length > 0 && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Дата и время</th>
                  <th scope="col">ID проверки</th>
                  <th scope="col">ID документа</th>
                  <th scope="col">Уверенность</th>
                  <th scope="col">Статус готовности</th>
                  <th scope="col">Экспертная проверка</th>
                  <th scope="col">Причины</th>
                  <th scope="col">Действие</th>
                </tr>
              </thead>
              <tbody>
                {state.data.items.map((review) => (
                  <tr key={review.id}>
                    <td>{formatDateTime(review.created_at)}</td>
                    <td>
                      <code className="id-cell">{review.id}</code>
                    </td>
                    <td>
                      <code className="id-cell">{review.document_id}</code>
                    </td>
                    <td>{labelConfidence(review.confidence)}</td>
                    <td>{labelReadiness(review.readiness)}</td>
                    <td>
                      {review.needs_review ? (
                        <span className="badge badge-warning">{labelNeedsReview(true)}</span>
                      ) : (
                        <span className="badge badge-neutral">{labelNeedsReview(false)}</span>
                      )}
                      {review.error && <div className="row-note">Есть техническое примечание</div>}
                    </td>
                    <td>
                      {review.reason_codes.length === 0 ? (
                        "—"
                      ) : (
                        <ul className="badge-list">
                          {review.reason_codes.map((code) => (
                            <li key={code}>
                              <span className="badge badge-neutral">{labelReasonCode(code)}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </td>
                    <td>
                      <Link to={`/reviews/${review.id}`} className="button button-secondary">
                        Открыть результат
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Rendered whenever a page has loaded, independent of the current
            page's item count — a `Pagination` gated on `items.length > 0`
            is exactly what strands a user on an out-of-range empty page
            with no visible way back. `total === 0` and `total > 0` both
            render here; `Pagination` itself derives its own button-disabled
            state from `total`/`limit`/`offset`, never from item count. */}
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

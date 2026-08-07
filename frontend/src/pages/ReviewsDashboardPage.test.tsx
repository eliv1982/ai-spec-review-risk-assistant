import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ReviewsDashboardPage } from "./ReviewsDashboardPage";
import { getApiBaseUrl } from "../api/client";
import { labelReasonCode } from "../utils/labels";
import { formatDateTime } from "../utils/formatting";
import type { FinalReview, ReviewResponse } from "../types/api";

// Derived from the real base-URL logic (not hardcoded) so the expected
// endpoint tracks whatever `getApiBaseUrl()` actually resolves to.
const REVIEWS_LIST_URL = new URL(`${getApiBaseUrl()}/reviews`);
const REVIEWS_LIST_ORIGIN = REVIEWS_LIST_URL.origin;
const REVIEWS_LIST_PATHNAME = REVIEWS_LIST_URL.pathname;
const REVIEWS_EXPORT_PATHNAME = `${REVIEWS_LIST_PATHNAME}/export`;

/** Throws unless the request is `GET <origin>/api/reviews` — so a
 * production regression (`/api/review`, `/api/audit-runs`, a missing
 * `/api` prefix, a doubled `/api/api/reviews`, or a non-GET method) makes
 * every test using this check fail loudly instead of silently returning a
 * mocked success envelope for whatever URL was actually requested. Method
 * defaults to GET, mirroring `fetch`'s own default when `init.method` is
 * omitted. */
function assertReviewsListRequest(input: RequestInfo | URL, init?: RequestInit): URL {
  const method = init?.method ?? "GET";
  if (method !== "GET") {
    throw new Error(`reviews list mock: expected GET, got ${method} for ${String(input)}`);
  }

  const url = new URL(input.toString());
  if (url.origin !== REVIEWS_LIST_ORIGIN || url.pathname !== REVIEWS_LIST_PATHNAME) {
    throw new Error(
      `reviews list mock: expected ${REVIEWS_LIST_ORIGIN}${REVIEWS_LIST_PATHNAME}, got ${url.origin}${url.pathname}`,
    );
  }

  return url;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function flushMicrotasks() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

const BASE_FINAL_REVIEW: Omit<FinalReview, "needs_review" | "review_reason_codes"> = {
  summary: "Резюме проверки для теста.",
  risks: [],
  missing_requirements: [],
  contradictions: [],
  questions_to_client: [],
  acceptance_criteria: [],
  confidence: "low",
  document_readiness: "not_ready",
};

function buildReview(overrides: {
  id: string;
  documentId?: string;
  needs_review: boolean;
  reason_codes: string[];
}): ReviewResponse {
  return {
    id: overrides.id,
    created_at: "2026-08-04T18:30:00Z",
    document_id: overrides.documentId ?? "doc-1",
    review_json: {
      ...BASE_FINAL_REVIEW,
      needs_review: overrides.needs_review,
      review_reason_codes: overrides.reason_codes,
    },
    confidence: "low",
    readiness: "not_ready",
    needs_review: overrides.needs_review,
    reason_codes: overrides.reason_codes,
    error: null,
  };
}

function paginated(
  items: ReviewResponse[],
  overrides: Partial<{ total: number; limit: number; offset: number }> = {},
) {
  return {
    items,
    total: overrides.total ?? items.length,
    limit: overrides.limit ?? 20,
    offset: overrides.offset ?? 0,
  };
}

/** A minimal, deterministic fake `GET /api/reviews`: slices `allItems` by the
 * requested `limit`/`offset` and applies `document_id`/`needs_review` the
 * same way the real backend does (docs/API_CONTRACTS.md). */
function mockReviewsApi(allItems: ReviewResponse[]) {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = assertReviewsListRequest(input, init);
    const limit = Number(url.searchParams.get("limit") ?? "20");
    const offset = Number(url.searchParams.get("offset") ?? "0");
    const documentId = url.searchParams.get("document_id");
    const needsReview = url.searchParams.get("needs_review");

    let filtered = allItems;
    if (documentId) filtered = filtered.filter((item) => item.document_id === documentId);
    if (needsReview !== null) filtered = filtered.filter((item) => String(item.needs_review) === needsReview);

    const page = filtered.slice(offset, offset + limit);
    return Promise.resolve(jsonResponse(paginated(page, { total: filtered.length, limit, offset })));
  });
}

function csvResponse(body: string, headers: Record<string, string> = {}, status = 200): Response {
  return new Response(body, {
    status,
    headers: { "Content-Type": "text/csv; charset=utf-8", ...headers },
  });
}

/** Routes `GET /api/reviews` through the same list logic as `mockReviewsApi`,
 * and `GET /api/reviews/export` through `exportHandler` — so a single fetch
 * mock can serve both the already-loaded table and an export click without
 * either request accidentally satisfying the other's expectations. */
function mockReviewsApiWithExport(
  allItems: ReviewResponse[],
  exportHandler: (url: URL) => Response | Promise<Response>,
) {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(input.toString());
    if (url.pathname === REVIEWS_EXPORT_PATHNAME) {
      const method = init?.method ?? "GET";
      if (method !== "GET") {
        throw new Error(`reviews export mock: expected GET, got ${method}`);
      }
      return Promise.resolve(exportHandler(url));
    }

    assertReviewsListRequest(input, init);
    const limit = Number(url.searchParams.get("limit") ?? "20");
    const offset = Number(url.searchParams.get("offset") ?? "0");
    const documentId = url.searchParams.get("document_id");
    const needsReview = url.searchParams.get("needs_review");

    let filtered = allItems;
    if (documentId) filtered = filtered.filter((item) => item.document_id === documentId);
    if (needsReview !== null) filtered = filtered.filter((item) => String(item.needs_review) === needsReview);

    const page = filtered.slice(offset, offset + limit);
    return Promise.resolve(jsonResponse(paginated(page, { total: filtered.length, limit, offset })));
  });
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/reviews"]}>
      <Routes>
        <Route path="/reviews" element={<ReviewsDashboardPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ReviewsDashboardPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("загружает и отображает список проверок под заголовком «История проверок»", async () => {
    vi.stubGlobal(
      "fetch",
      mockReviewsApi([
        buildReview({ id: "review-1", needs_review: true, reason_codes: ["LOW_CONFIDENCE"] }),
        buildReview({ id: "review-2", needs_review: false, reason_codes: [] }),
      ]),
    );

    renderPage();

    expect(screen.getByRole("heading", { name: "История проверок", level: 1 })).toBeInTheDocument();

    const table = await screen.findByRole("table");
    expect(within(table).getByText("review-1")).toBeInTheDocument();
    expect(within(table).getByText("review-2")).toBeInTheDocument();
  });

  it("подключает таблицу к локализованным значениям (дата, уверенность, готовность, причина) вместо сырых enum", async () => {
    const review: ReviewResponse = {
      id: "review-medium",
      created_at: "2026-08-04T18:30:00Z",
      document_id: "doc-1",
      review_json: {
        ...BASE_FINAL_REVIEW,
        confidence: "medium",
        document_readiness: "needs_clarification",
        needs_review: true,
        review_reason_codes: ["LOW_CONFIDENCE"],
      },
      confidence: "medium",
      readiness: "needs_clarification",
      needs_review: true,
      reason_codes: ["LOW_CONFIDENCE"],
      error: null,
    };

    vi.stubGlobal("fetch", mockReviewsApi([review]));

    renderPage();

    const table = await screen.findByRole("table");
    expect(within(table).getByText(formatDateTime("2026-08-04T18:30:00Z"))).toBeInTheDocument();
    expect(within(table).getByText("Средняя")).toBeInTheDocument();
    expect(within(table).getByText("Требует уточнений")).toBeInTheDocument();
    expect(within(table).getByText(labelReasonCode("LOW_CONFIDENCE"))).toBeInTheDocument();
    expect(within(table).getByText("Нужна экспертная проверка")).toBeInTheDocument();

    // The business table cells must never leak the raw backend enum/code
    // values — only their localized Russian labels.
    expect(within(table).queryByText("medium")).not.toBeInTheDocument();
    expect(within(table).queryByText("needs_clarification")).not.toBeInTheDocument();
    expect(within(table).queryByText("LOW_CONFIDENCE")).not.toBeInTheDocument();
  });

  it("REGRESSION: начальная загрузка отправляет точный запрос GET http://127.0.0.1:8000/api/reviews?limit=20&offset=0", async () => {
    const fetchMock = mockReviewsApi([]);
    vi.stubGlobal("fetch", fetchMock);

    renderPage();
    await screen.findByText("По заданным фильтрам проверки не найдены.");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect((init?.method ?? "GET")).toBe("GET");
    expect(String(url)).toBe("http://127.0.0.1:8000/api/reviews?limit=20&offset=0");
  });

  it("needs_review=true хорошо заметен («Нужна экспертная проверка»)", async () => {
    vi.stubGlobal(
      "fetch",
      mockReviewsApi([buildReview({ id: "review-1", needs_review: true, reason_codes: ["LOW_CONFIDENCE"] })]),
    );

    renderPage();

    const table = await screen.findByRole("table");
    expect(within(table).getByText("Нужна экспертная проверка")).toBeInTheDocument();
  });

  it("needs_review=false отображается нейтрально («Экспертная проверка не требуется»)", async () => {
    vi.stubGlobal(
      "fetch",
      mockReviewsApi([buildReview({ id: "review-1", needs_review: false, reason_codes: [] })]),
    );

    renderPage();

    const table = await screen.findByRole("table");
    expect(within(table).getByText("Экспертная проверка не требуется")).toBeInTheDocument();
    expect(within(table).queryByText("Нужна экспертная проверка")).not.toBeInTheDocument();
  });

  it("переход «Открыть результат» использует точный review id", async () => {
    vi.stubGlobal(
      "fetch",
      mockReviewsApi([buildReview({ id: "review-exact-id", needs_review: false, reason_codes: [] })]),
    );

    renderPage();

    const link = await screen.findByRole("link", { name: "Открыть результат" });
    expect(link).toHaveAttribute("href", "/reviews/review-exact-id");
  });

  it("document_id filter отправляется в API", async () => {
    const fetchMock = mockReviewsApi([
      buildReview({ id: "review-a", documentId: "doc-a", needs_review: false, reason_codes: [] }),
      buildReview({ id: "review-b", documentId: "doc-b", needs_review: false, reason_codes: [] }),
    ]);
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("table");

    await user.type(screen.getByLabelText("Идентификатор документа"), "doc-b");
    await user.click(screen.getByRole("button", { name: "Применить" }));

    const table = await screen.findByRole("table");
    expect(within(table).getByText("review-b")).toBeInTheDocument();
    expect(within(table).queryByText("review-a")).not.toBeInTheDocument();

    const lastCall = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
    const url = new URL(String(lastCall[0]));
    expect(url.searchParams.get("document_id")).toBe("doc-b");
  });

  it("needs_review filter отправляется в API", async () => {
    const fetchMock = mockReviewsApi([
      buildReview({ id: "review-true", needs_review: true, reason_codes: ["LOW_CONFIDENCE"] }),
      buildReview({ id: "review-false", needs_review: false, reason_codes: [] }),
    ]);
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("table");

    await user.selectOptions(screen.getByLabelText("Экспертная проверка"), "true");
    await user.click(screen.getByRole("button", { name: "Применить" }));

    const table = await screen.findByRole("table");
    expect(within(table).getByText("review-true")).toBeInTheDocument();
    expect(within(table).queryByText("review-false")).not.toBeInTheDocument();

    const lastCall = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
    const url = new URL(String(lastCall[0]));
    expect(url.searchParams.get("needs_review")).toBe("true");
  });

  it("needs_review=false формирует точный query needs_review=false", async () => {
    const fetchMock = mockReviewsApi([
      buildReview({ id: "review-true", needs_review: true, reason_codes: ["LOW_CONFIDENCE"] }),
      buildReview({ id: "review-false", needs_review: false, reason_codes: [] }),
    ]);
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("table");

    await user.selectOptions(screen.getByLabelText("Экспертная проверка"), "false");
    await user.click(screen.getByRole("button", { name: "Применить" }));

    const table = await screen.findByRole("table");
    expect(within(table).getByText("review-false")).toBeInTheDocument();
    expect(within(table).queryByText("review-true")).not.toBeInTheDocument();

    const lastCall = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
    const url = new URL(String(lastCall[0]));
    expect(url.searchParams.get("needs_review")).toBe("false");
  });

  it("«Сбросить фильтры» очищает document_id/needs_review и offset, новый URL не содержит старых параметров", async () => {
    const items = Array.from({ length: 25 }, (_, index) =>
      buildReview({ id: `review-${index}`, documentId: "doc-a", needs_review: true, reason_codes: [] }),
    );
    const fetchMock = mockReviewsApi(items);
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("table");

    await user.type(screen.getByLabelText("Идентификатор документа"), "doc-a");
    await user.selectOptions(screen.getByLabelText("Экспертная проверка"), "true");
    await user.click(screen.getByRole("button", { name: "Применить" }));
    await user.click(screen.getByRole("button", { name: "Далее" }));
    await screen.findByText(/показаны 21–25 из 25/i);

    let lastCall = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
    let url = new URL(String(lastCall[0]));
    expect(url.searchParams.get("document_id")).toBe("doc-a");
    expect(url.searchParams.get("needs_review")).toBe("true");
    expect(url.searchParams.get("offset")).toBe("20");

    await user.click(screen.getByRole("button", { name: "Сбросить фильтры" }));
    await screen.findByText(/показаны 1–20 из 25/i);

    lastCall = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
    url = new URL(String(lastCall[0]));
    expect(url.searchParams.has("document_id")).toBe(false);
    expect(url.searchParams.has("needs_review")).toBe(false);
    expect(url.searchParams.get("offset")).toBe("0");
    expect((screen.getByLabelText("Идентификатор документа") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("Экспертная проверка") as HTMLSelectElement).value).toBe("all");
  });

  it("stale late error: устаревший запрос завершается ошибкой после успешного нового — актуальные данные остаются, banner не появляется", async () => {
    const deferred1 = createDeferred<Response>();
    const deferred2 = createDeferred<Response>();
    let callCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        assertReviewsListRequest(input, init);
        callCount += 1;
        if (callCount === 1) return deferred1.promise;
        if (callCount === 2) return deferred2.promise;
        return Promise.reject(new Error("unexpected extra fetch call"));
      }),
    );

    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/загружаем список проверок/i);

    await user.type(screen.getByLabelText("Идентификатор документа"), "doc-b");
    await user.click(screen.getByRole("button", { name: "Применить" }));

    deferred2.resolve(
      jsonResponse(
        paginated([buildReview({ id: "review-b", documentId: "doc-b", needs_review: false, reason_codes: [] })]),
      ),
    );
    await screen.findByRole("table");

    deferred1.reject(new Error("boom: stale network failure"));
    await flushMicrotasks();

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("review-b")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText("Не удалось загрузить список проверок")).not.toBeInTheDocument();
  });

  it("out-of-range: offset=20 и total упал до 15 -> коррекция на offset=0 и отображение первой страницы", async () => {
    let offsetZeroCalls = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = assertReviewsListRequest(input, init);
      const offset = Number(url.searchParams.get("offset") ?? "0");
      if (offset === 20) {
        // The second page is now empty — total shrank to 15 since this offset was requested.
        return Promise.resolve(jsonResponse(paginated([], { total: 15, limit: 20, offset: 20 })));
      }
      if (offset === 0) {
        offsetZeroCalls += 1;
        if (offsetZeroCalls === 1) {
          const items = Array.from({ length: 20 }, (_, i) =>
            buildReview({ id: `review-${i}`, needs_review: false, reason_codes: [] }),
          );
          return Promise.resolve(jsonResponse(paginated(items, { total: 25, limit: 20, offset: 0 })));
        }
        const items = Array.from({ length: 15 }, (_, i) =>
          buildReview({ id: `review-${i}`, needs_review: false, reason_codes: [] }),
        );
        return Promise.resolve(jsonResponse(paginated(items, { total: 15, limit: 20, offset: 0 })));
      }
      return Promise.reject(new Error(`unexpected offset: ${offset}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("table");

    await user.click(screen.getByRole("button", { name: "Далее" }));

    // No dead-end empty state for the out-of-range page: the frontend
    // corrects offset to 0 and shows the first page of the shrunk result set.
    await screen.findByText(/показаны 1–15 из 15/i);
    const table = screen.getByRole("table");
    expect(within(table).getByText("review-0")).toBeInTheDocument();
    expect(screen.queryByText("По заданным фильтрам проверки не найдены.")).not.toBeInTheDocument();

    const offsetZeroRequests = fetchMock.mock.calls.filter(
      ([url]) => new URL(String(url)).searchParams.get("offset") === "0",
    );
    expect(offsetZeroRequests).toHaveLength(2); // initial load + corrected reload, no loop
  });

  it("out-of-range: offset=40, total=25 -> корректный новый offset=20", async () => {
    let offset20Calls = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = assertReviewsListRequest(input, init);
      const offset = Number(url.searchParams.get("offset") ?? "0");
      const makeItems = (count: number, prefix: string) =>
        Array.from({ length: count }, (_, i) => buildReview({ id: `${prefix}-${i}`, needs_review: false, reason_codes: [] }));

      if (offset === 0) return Promise.resolve(jsonResponse(paginated(makeItems(20, "p1"), { total: 45, limit: 20, offset: 0 })));
      if (offset === 40) return Promise.resolve(jsonResponse(paginated([], { total: 25, limit: 20, offset: 40 })));
      if (offset === 20) {
        offset20Calls += 1;
        if (offset20Calls === 1) {
          return Promise.resolve(jsonResponse(paginated(makeItems(20, "p2"), { total: 45, limit: 20, offset: 20 })));
        }
        return Promise.resolve(jsonResponse(paginated(makeItems(5, "p2b"), { total: 25, limit: 20, offset: 20 })));
      }
      return Promise.reject(new Error(`unexpected offset: ${offset}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("table");

    await user.click(screen.getByRole("button", { name: "Далее" })); // offset 0 -> 20
    await screen.findByText(/показаны 21–40 из 45/i);
    await user.click(screen.getByRole("button", { name: "Далее" })); // offset 20 -> 40

    // offset=40 came back empty (total shrank to 25): corrects to offset=20.
    await screen.findByText(/показаны 21–25 из 25/i);
    const table = screen.getByRole("table");
    expect(within(table).getByText("p2b-0")).toBeInTheDocument();

    const offset40Requests = fetchMock.mock.calls.filter(
      ([url]) => new URL(String(url)).searchParams.get("offset") === "40",
    );
    expect(offset40Requests).toHaveLength(1); // no repeated/looping requests at the invalid offset
  });

  it("out-of-range: total=0 -> offset сбрасывается в 0, без бесконечных запросов, нормальное пустое состояние", async () => {
    let offsetZeroCalls = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = assertReviewsListRequest(input, init);
      const offset = Number(url.searchParams.get("offset") ?? "0");
      if (offset === 0) {
        offsetZeroCalls += 1;
        if (offsetZeroCalls === 1) {
          const items = Array.from({ length: 20 }, (_, i) =>
            buildReview({ id: `review-${i}`, needs_review: false, reason_codes: [] }),
          );
          return Promise.resolve(jsonResponse(paginated(items, { total: 25, limit: 20, offset: 0 })));
        }
        // Corrected reload: all rows were deleted in the meantime.
        return Promise.resolve(jsonResponse(paginated([], { total: 0, limit: 20, offset: 0 })));
      }
      // All rows were deleted while the user was on page 2: total is now 0.
      return Promise.resolve(jsonResponse(paginated([], { total: 0, limit: 20, offset })));
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("table");

    await user.click(screen.getByRole("button", { name: "Далее" }));

    expect(await screen.findByText("По заданным фильтрам проверки не найдены.")).toBeInTheDocument();
    expect(await screen.findByText("Нет записей")).toBeInTheDocument();
    // Exactly 3 requests: initial (offset=0), page-2 (offset=20, now empty),
    // corrected reload (offset=0) — no infinite retry loop.
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("изменение фильтра сбрасывает offset на 0", async () => {
    const items = Array.from({ length: 25 }, (_, index) =>
      buildReview({ id: `review-${index}`, needs_review: false, reason_codes: [] }),
    );
    const fetchMock = mockReviewsApi(items);
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("table");

    await user.click(screen.getByRole("button", { name: "Далее" }));
    await screen.findByText(/показаны 21–25 из 25/i);

    let lastCall = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
    expect(new URL(String(lastCall[0])).searchParams.get("offset")).toBe("20");

    await user.type(screen.getByLabelText("Идентификатор документа"), "doc-1");
    await user.click(screen.getByRole("button", { name: "Применить" }));

    await screen.findByText(/показаны 1–20 из 25/i);
    lastCall = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
    expect(new URL(String(lastCall[0])).searchParams.get("offset")).toBe("0");
  });

  it("пагинация «Далее»/«Назад» использует точные limit/offset", async () => {
    const items = Array.from({ length: 25 }, (_, index) =>
      buildReview({ id: `review-${index}`, needs_review: false, reason_codes: [] }),
    );
    const fetchMock = mockReviewsApi(items);
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("table");
    expect(screen.getByRole("button", { name: "Назад" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Далее" }));
    await screen.findByText(/показаны 21–25 из 25/i);
    let call = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
    let url = new URL(String(call[0]));
    expect(url.searchParams.get("limit")).toBe("20");
    expect(url.searchParams.get("offset")).toBe("20");
    expect(screen.getByRole("button", { name: "Далее" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Назад" }));
    await screen.findByText(/показаны 1–20 из 25/i);
    call = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
    url = new URL(String(call[0]));
    expect(url.searchParams.get("limit")).toBe("20");
    expect(url.searchParams.get("offset")).toBe("0");
  });

  it("показывает нейтральное сообщение при пустом списке", async () => {
    vi.stubGlobal("fetch", mockReviewsApi([]));

    renderPage();

    expect(await screen.findByText("По заданным фильтрам проверки не найдены.")).toBeInTheDocument();
  });

  it("показывает русскоязычную ошибку при сбое API", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(jsonResponse({ detail: "Внутренняя ошибка сервера" }, 500))),
    );

    renderPage();

    expect(await screen.findByText("Внутренняя ошибка сервера")).toBeInTheDocument();
    expect(screen.getByText("Не удалось загрузить список проверок")).toBeInTheDocument();
  });

  it("stale-ответ при быстрой смене фильтра не перезаписывает актуальный список", async () => {
    const deferred1 = createDeferred<Response>();
    const deferred2 = createDeferred<Response>();
    let callCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        assertReviewsListRequest(input, init);
        callCount += 1;
        if (callCount === 1) return deferred1.promise;
        if (callCount === 2) return deferred2.promise;
        return Promise.reject(new Error("unexpected extra fetch call"));
      }),
    );

    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/загружаем список проверок/i);

    await user.type(screen.getByLabelText("Идентификатор документа"), "doc-b");
    await user.click(screen.getByRole("button", { name: "Применить" }));

    // The newer (filtered) request resolves first.
    deferred2.resolve(
      jsonResponse(
        paginated([buildReview({ id: "review-b", documentId: "doc-b", needs_review: false, reason_codes: [] })]),
      ),
    );
    await screen.findByRole("table");

    // The superseded initial request resolves late with different data —
    // it must be ignored, not overwrite the already-current filtered list.
    deferred1.resolve(
      jsonResponse(
        paginated([buildReview({ id: "review-a", documentId: "doc-a", needs_review: false, reason_codes: [] })]),
      ),
    );
    await flushMicrotasks();

    const table = screen.getByRole("table");
    expect(within(table).getByText("review-b")).toBeInTheDocument();
    expect(within(table).queryByText("review-a")).not.toBeInTheDocument();
  });
});

describe("ReviewsDashboardPage — экспорт CSV", () => {
  let anchorClickSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    // jsdom has no real `URL.createObjectURL`/`revokeObjectURL` — add them
    // directly onto the real `URL` constructor (never replace the global
    // itself, which `getApiBaseUrl()`'s own `new URL(...)` call still needs)
    // so `downloadBlob` on a successful export does not throw and get
    // misread as an export failure.
    (URL as unknown as { createObjectURL: unknown }).createObjectURL = vi.fn(() => "blob:mock-url");
    (URL as unknown as { revokeObjectURL: unknown }).revokeObjectURL = vi.fn();
    // jsdom actually attempts to navigate on a real `<a href>` click, which it
    // doesn't implement and logs as a noisy (non-failing) error. The actual
    // click/cleanup mechanics of `downloadBlob` are already covered by
    // src/utils/download.test.ts; here only the page's own export
    // request/state wiring is under test.
    anchorClickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    delete (URL as unknown as { createObjectURL?: unknown }).createObjectURL;
    delete (URL as unknown as { revokeObjectURL?: unknown }).revokeObjectURL;
    anchorClickSpy.mockRestore();
  });

  it("кнопка «Скачать CSV» видна после загрузки списка", async () => {
    vi.stubGlobal("fetch", mockReviewsApiWithExport([], () => csvResponse("header\r\n")));

    renderPage();
    await screen.findByText("По заданным фильтрам проверки не найдены.");

    expect(screen.getByRole("button", { name: "Скачать CSV" })).toBeInTheDocument();
  });

  it("экспорт использует текущие применённые фильтры и не включает limit/offset", async () => {
    const fetchMock = mockReviewsApiWithExport(
      [
        buildReview({ id: "review-a", documentId: "doc-a", needs_review: true, reason_codes: ["LOW_CONFIDENCE"] }),
      ],
      () => csvResponse("header\r\n"),
    );
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("table");

    await user.type(screen.getByLabelText("Идентификатор документа"), "doc-a");
    await user.selectOptions(screen.getByLabelText("Экспертная проверка"), "true");
    await user.click(screen.getByRole("button", { name: "Применить" }));
    await screen.findByRole("table");

    await user.click(screen.getByRole("button", { name: "Скачать CSV" }));
    await screen.findByRole("button", { name: "Скачать CSV" });

    const exportCall = fetchMock.mock.calls.find(
      ([url]) => new URL(String(url)).pathname === REVIEWS_EXPORT_PATHNAME,
    );
    expect(exportCall).toBeDefined();
    const exportUrl = new URL(String(exportCall![0]));
    expect(exportUrl.searchParams.get("document_id")).toBe("doc-a");
    expect(exportUrl.searchParams.get("needs_review")).toBe("true");
    expect(exportUrl.searchParams.has("limit")).toBe(false);
    expect(exportUrl.searchParams.has("offset")).toBe(false);
  });

  it("кнопка отключена во время формирования CSV и текст меняется", async () => {
    const deferred = createDeferred<Response>();
    const fetchMock = mockReviewsApiWithExport([], () => deferred.promise);
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderPage();
    await screen.findByText("По заданным фильтрам проверки не найдены.");

    const button = screen.getByRole("button", { name: "Скачать CSV" });
    await user.click(button);

    expect(await screen.findByRole("button", { name: "Формируется CSV…" })).toBeDisabled();

    deferred.resolve(csvResponse("header\r\n"));
    await screen.findByRole("button", { name: "Скачать CSV" });
    expect(screen.getByRole("button", { name: "Скачать CSV" })).not.toBeDisabled();
  });

  it("двойной клик не запускает два экспорт-запроса", async () => {
    const deferred = createDeferred<Response>();
    let exportCalls = 0;
    const fetchMock = mockReviewsApiWithExport([], () => {
      exportCalls += 1;
      return deferred.promise;
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderPage();
    await screen.findByText("По заданным фильтрам проверки не найдены.");

    const button = screen.getByRole("button", { name: "Скачать CSV" });
    await user.click(button);
    await user.click(button); // second click while pending must be a no-op

    expect(exportCalls).toBe(1);

    deferred.resolve(csvResponse("header\r\n"));
    await screen.findByRole("button", { name: "Скачать CSV" });
  });

  it("успешный экспорт запускает скачивание ровно один раз и не показывает ошибку", async () => {
    vi.stubGlobal("fetch", mockReviewsApiWithExport([], () => csvResponse("header\r\n")));

    const user = userEvent.setup();
    renderPage();
    await screen.findByText("По заданным фильтрам проверки не найдены.");

    await user.click(screen.getByRole("button", { name: "Скачать CSV" }));
    await screen.findByRole("button", { name: "Скачать CSV" });

    // Positive assertion: the download was actually triggered exactly once —
    // not merely "no error appeared", which would also pass if downloadBlob
    // were never called at all.
    expect(anchorClickSpy).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Не удалось сформировать CSV-файл")).not.toBeInTheDocument();

    // No further download after the pending promise has already settled.
    await flushMicrotasks();
    expect(anchorClickSpy).toHaveBeenCalledTimes(1);
  });

  it("ошибка экспорта показывается отдельно и не стирает уже загруженную таблицу", async () => {
    const fetchMock = mockReviewsApiWithExport(
      [buildReview({ id: "review-a", needs_review: false, reason_codes: [] })],
      () => jsonResponse({ detail: "Внутренняя ошибка сервера" }, 500),
    );
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderPage();
    const table = await screen.findByRole("table");
    expect(within(table).getByText("review-a")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Скачать CSV" }));

    expect(await screen.findByText("Не удалось сформировать CSV-файл")).toBeInTheDocument();
    expect(screen.getByText("Внутренняя ошибка сервера")).toBeInTheDocument();
    // The table (from the earlier successful list load) is still intact.
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getByText("review-a")).toBeInTheDocument();
  });

  it("повторный клик после ошибки экспорта работает (retry)", async () => {
    let exportCalls = 0;
    const fetchMock = mockReviewsApiWithExport([], () => {
      exportCalls += 1;
      if (exportCalls === 1) return jsonResponse({ detail: "Внутренняя ошибка сервера" }, 500);
      return csvResponse("header\r\n");
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderPage();
    await screen.findByText("По заданным фильтрам проверки не найдены.");

    await user.click(screen.getByRole("button", { name: "Скачать CSV" }));
    await screen.findByText("Не удалось сформировать CSV-файл");

    await user.click(screen.getByRole("button", { name: "Скачать CSV" }));
    await screen.findByRole("button", { name: "Скачать CSV" });

    expect(screen.queryByText("Не удалось сформировать CSV-файл")).not.toBeInTheDocument();
    expect(exportCalls).toBe(2);
  });

  it("unmount во время формирования CSV: скачивание не запускается, state не обновляется, warning не выводится", async () => {
    const deferred = createDeferred<Response>();
    const fetchMock = mockReviewsApiWithExport([], () => deferred.promise);
    vi.stubGlobal("fetch", fetchMock);
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const user = userEvent.setup();
    const view = renderPage();
    await screen.findByText("По заданным фильтрам проверки не найдены.");

    await user.click(screen.getByRole("button", { name: "Скачать CSV" }));
    await screen.findByRole("button", { name: "Формируется CSV…" });

    view.unmount();

    // The export request resolves only after unmount — the pending request
    // is allowed to complete, but its result must be ignored: no download,
    // no state update, no React "state update on an unmounted component"
    // warning.
    deferred.resolve(csvResponse("header\r\n"));
    await flushMicrotasks();

    expect(anchorClickSpy).not.toHaveBeenCalled();
    const stateUpdateWarning = consoleErrorSpy.mock.calls.some(([message]) =>
      String(message).includes("unmounted component"),
    );
    expect(stateUpdateWarning).toBe(false);

    consoleErrorSpy.mockRestore();
  });

  it("unmount во время формирования CSV: последующий reject не запускает скачивание и не выводит warning", async () => {
    const deferred = createDeferred<Response>();
    const fetchMock = mockReviewsApiWithExport([], () => deferred.promise);
    vi.stubGlobal("fetch", fetchMock);
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const user = userEvent.setup();
    const view = renderPage();
    await screen.findByText("По заданным фильтрам проверки не найдены.");

    await user.click(screen.getByRole("button", { name: "Скачать CSV" }));
    await screen.findByRole("button", { name: "Формируется CSV…" });

    view.unmount();

    // The export request rejects only after unmount — this must not throw
    // out of the test (the rejection is awaited via flushMicrotasks below,
    // so it can never surface as an unhandled rejection), must not trigger a
    // download, and must not attempt any post-unmount UI update.
    deferred.reject(new Error("boom: late rejection after unmount"));
    await flushMicrotasks();

    expect(anchorClickSpy).not.toHaveBeenCalled();
    const stateUpdateWarning = consoleErrorSpy.mock.calls.some(([message]) =>
      String(message).includes("unmounted component"),
    );
    expect(stateUpdateWarning).toBe(false);

    consoleErrorSpy.mockRestore();
  });
});

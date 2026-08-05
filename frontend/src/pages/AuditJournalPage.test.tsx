import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AuditJournalPage } from "./AuditJournalPage";
import { getApiBaseUrl } from "../api/client";
import type { AuditRunResponse, AuditStatus } from "../types/api";

// Derived from the real base-URL logic (not hardcoded) so the expected
// endpoint tracks whatever `getApiBaseUrl()` actually resolves to.
const AUDIT_LIST_URL = new URL(`${getApiBaseUrl()}/audit-runs`);
const AUDIT_LIST_ORIGIN = AUDIT_LIST_URL.origin;
const AUDIT_LIST_PATHNAME = AUDIT_LIST_URL.pathname;

/** Throws unless the request is `GET <origin>/api/audit-runs` — so a
 * production regression (`/api/audit`, `/api/reviews`, a missing `/api`
 * prefix, a doubled `/api/api/audit-runs`, or a non-GET method) makes every
 * test using this check fail loudly instead of silently returning a mocked
 * success envelope for whatever URL was actually requested. Also enforces
 * the API contract that `status` and `errors_only` are never sent together
 * (docs/API_CONTRACTS.md). Method defaults to GET, mirroring `fetch`'s own
 * default when `init.method` is omitted. */
function assertAuditListRequest(input: RequestInfo | URL, init?: RequestInit): URL {
  const method = init?.method ?? "GET";
  if (method !== "GET") {
    throw new Error(`audit list mock: expected GET, got ${method} for ${String(input)}`);
  }

  const url = new URL(input.toString());
  if (url.origin !== AUDIT_LIST_ORIGIN || url.pathname !== AUDIT_LIST_PATHNAME) {
    throw new Error(
      `audit list mock: expected ${AUDIT_LIST_ORIGIN}${AUDIT_LIST_PATHNAME}, got ${url.origin}${url.pathname}`,
    );
  }

  if (url.searchParams.has("status") && url.searchParams.has("errors_only")) {
    throw new Error(`audit list mock: status and errors_only must not both be present: ${url.search}`);
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

function buildAuditRun(overrides: {
  id: string;
  action?: string;
  status: AuditStatus;
  entity_type?: string | null;
  entity_id?: string | null;
  input_json?: Record<string, unknown> | null;
  output_json?: Record<string, unknown> | null;
  error?: string | null;
  duration_ms?: number;
}): AuditRunResponse {
  return {
    id: overrides.id,
    created_at: "2026-08-04T18:30:00Z",
    action: overrides.action ?? "document.review",
    entity_type: overrides.entity_type ?? "review",
    entity_id: overrides.entity_id ?? overrides.id,
    input_json: overrides.input_json ?? null,
    output_json: overrides.output_json ?? null,
    status: overrides.status,
    error: overrides.error ?? (overrides.status === "error" ? "Техническая ошибка выполнения" : null),
    duration_ms: overrides.duration_ms ?? 120,
  };
}

function paginated(
  items: AuditRunResponse[],
  overrides: Partial<{ total: number; limit: number; offset: number }> = {},
) {
  return {
    items,
    total: overrides.total ?? items.length,
    limit: overrides.limit ?? 20,
    offset: overrides.offset ?? 0,
  };
}

/** A minimal, deterministic fake `GET /api/audit-runs`, mirroring the real
 * backend's `status`/`errors_only`/`limit`/`offset` semantics (docs/API_CONTRACTS.md). */
function mockAuditApi(allItems: AuditRunResponse[]) {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = assertAuditListRequest(input, init);
    const limit = Number(url.searchParams.get("limit") ?? "20");
    const offset = Number(url.searchParams.get("offset") ?? "0");
    const status = url.searchParams.get("status");
    const errorsOnly = url.searchParams.get("errors_only") === "true";

    let filtered = allItems;
    if (status) filtered = filtered.filter((item) => item.status === status);
    if (errorsOnly) filtered = filtered.filter((item) => item.status === "error");

    const page = filtered.slice(offset, offset + limit);
    return Promise.resolve(jsonResponse(paginated(page, { total: filtered.length, limit, offset })));
  });
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/audit"]}>
      <Routes>
        <Route path="/audit" element={<AuditJournalPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("AuditJournalPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("записи журнала загружаются и отображаются", async () => {
    vi.stubGlobal(
      "fetch",
      mockAuditApi([
        buildAuditRun({ id: "audit-1", action: "document.review", status: "success" }),
        buildAuditRun({ id: "audit-2", action: "document.create", status: "success" }),
      ]),
    );

    renderPage();

    const table = await screen.findByRole("table");
    expect(within(table).getByText("document.review")).toBeInTheDocument();
    expect(within(table).getByText("document.create")).toBeInTheDocument();
  });

  it("REGRESSION: начальная загрузка отправляет точный запрос GET http://127.0.0.1:8000/api/audit-runs?limit=20&offset=0", async () => {
    const fetchMock = mockAuditApi([]);
    vi.stubGlobal("fetch", fetchMock);

    renderPage();
    await screen.findByText("По заданному фильтру записи аудита не найдены.");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect((init?.method ?? "GET")).toBe("GET");
    expect(String(url)).toBe("http://127.0.0.1:8000/api/audit-runs?limit=20&offset=0");
  });

  it("статус error отображается как техническая ошибка", async () => {
    vi.stubGlobal(
      "fetch",
      mockAuditApi([buildAuditRun({ id: "audit-err", status: "error", error: "Сбой модели" })]),
    );

    renderPage();

    const table = await screen.findByRole("table");
    expect(within(table).getByText("Техническая ошибка")).toBeInTheDocument();
    expect(within(table).getByText("Сбой модели")).toBeInTheDocument();
  });

  it("needs_review отображается отдельно от error, не как техническая ошибка", async () => {
    vi.stubGlobal(
      "fetch",
      mockAuditApi([
        buildAuditRun({ id: "audit-nr", status: "needs_review", entity_id: "review-nr" }),
        buildAuditRun({ id: "audit-err", status: "error", entity_id: "review-err", error: "Сбой модели" }),
      ]),
    );

    renderPage();

    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row");
    const nrRow = rows.find((row) => within(row).queryByText("review-nr"));
    const errRow = rows.find((row) => within(row).queryByText("review-err"));
    expect(nrRow).toBeDefined();
    expect(errRow).toBeDefined();

    expect(within(nrRow!).getByText("Требуется ручная проверка")).toBeInTheDocument();
    expect(within(nrRow!).queryByText("Техническая ошибка")).not.toBeInTheDocument();

    expect(within(errRow!).getByText("Техническая ошибка")).toBeInTheDocument();
    expect(within(errRow!).queryByText("Требуется ручная проверка")).not.toBeInTheDocument();
  });

  it("«Только ошибки» формирует запрос с errors_only=true", async () => {
    const fetchMock = mockAuditApi([
      buildAuditRun({ id: "audit-ok", status: "success" }),
      buildAuditRun({ id: "audit-err", status: "error" }),
    ]);
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("table");

    await user.selectOptions(screen.getByLabelText("Статус"), "error");

    const table = await screen.findByRole("table");
    expect(within(table).getByText("audit-err")).toBeInTheDocument();
    expect(within(table).queryByText("audit-ok")).not.toBeInTheDocument();

    const lastCall = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
    const url = new URL(String(lastCall[0]));
    expect(url.searchParams.get("errors_only")).toBe("true");
    expect(url.searchParams.get("status")).toBeNull();
  });

  it("status filter формирует точный query (status=success)", async () => {
    const fetchMock = mockAuditApi([
      buildAuditRun({ id: "audit-ok", status: "success" }),
      buildAuditRun({ id: "audit-nr", status: "needs_review" }),
    ]);
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("table");

    await user.selectOptions(screen.getByLabelText("Статус"), "success");
    await screen.findByRole("table");

    const lastCall = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
    const url = new URL(String(lastCall[0]));
    expect(url.searchParams.get("status")).toBe("success");
    expect(url.searchParams.get("errors_only")).toBeNull();
  });

  it("status filter формирует точный query (status=needs_review)", async () => {
    const fetchMock = mockAuditApi([
      buildAuditRun({ id: "audit-nr", status: "needs_review" }),
      buildAuditRun({ id: "audit-ok", status: "success" }),
    ]);
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("table");

    await user.selectOptions(screen.getByLabelText("Статус"), "needs_review");

    const table = await screen.findByRole("table");
    expect(within(table).getByText("audit-nr")).toBeInTheDocument();
    expect(within(table).queryByText("audit-ok")).not.toBeInTheDocument();

    const lastCall = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
    const url = new URL(String(lastCall[0]));
    expect(url.searchParams.get("status")).toBe("needs_review");
    expect(url.searchParams.get("errors_only")).toBeNull();
  });

  it("«Сбросить фильтры» не отправляет status/errors_only и сбрасывает offset", async () => {
    const items = Array.from({ length: 25 }, (_, index) => buildAuditRun({ id: `audit-${index}`, status: "error" }));
    const fetchMock = mockAuditApi(items);
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("table");

    await user.selectOptions(screen.getByLabelText("Статус"), "error");
    await screen.findByText(/показаны 1–20 из 25/i);
    await user.click(screen.getByRole("button", { name: "Далее" }));
    await screen.findByText(/показаны 21–25 из 25/i);

    let lastCall = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
    let url = new URL(String(lastCall[0]));
    expect(url.searchParams.get("errors_only")).toBe("true");
    expect(url.searchParams.get("offset")).toBe("20");

    await user.click(screen.getByRole("button", { name: "Сбросить фильтры" }));
    await screen.findByText(/показаны 1–20 из 25/i);

    lastCall = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
    url = new URL(String(lastCall[0]));
    expect(url.searchParams.has("status")).toBe(false);
    expect(url.searchParams.has("errors_only")).toBe(false);
    expect(url.searchParams.get("offset")).toBe("0");
    expect((screen.getByLabelText("Статус") as HTMLSelectElement).value).toBe("all");
  });

  it("изменение фильтра сбрасывает offset на 0", async () => {
    const items = Array.from({ length: 25 }, (_, index) => buildAuditRun({ id: `audit-${index}`, status: "success" }));
    const fetchMock = mockAuditApi(items);
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("table");

    await user.click(screen.getByRole("button", { name: "Далее" }));
    await screen.findByText(/показаны 21–25 из 25/i);
    let lastCall = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
    expect(new URL(String(lastCall[0])).searchParams.get("offset")).toBe("20");

    await user.selectOptions(screen.getByLabelText("Статус"), "success");

    await screen.findByText(/показаны 1–20 из 25/i);
    lastCall = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
    expect(new URL(String(lastCall[0])).searchParams.get("offset")).toBe("0");
  });

  it("пагинация «Далее»/«Назад» использует точные limit/offset, Next заблокирован на последней странице", async () => {
    const items = Array.from({ length: 25 }, (_, index) =>
      buildAuditRun({ id: `audit-${index}`, status: "success" }),
    );
    const fetchMock = mockAuditApi(items);
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

  it("показывает нейтральное сообщение при пустом журнале", async () => {
    vi.stubGlobal("fetch", mockAuditApi([]));

    renderPage();

    expect(await screen.findByText("По заданному фильтру записи аудита не найдены.")).toBeInTheDocument();
  });

  it("показывает русскоязычную ошибку при сбое API", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(jsonResponse({ detail: "Внутренняя ошибка сервера" }, 500))),
    );

    renderPage();

    expect(await screen.findByText("Внутренняя ошибка сервера")).toBeInTheDocument();
    expect(screen.getByText("Не удалось загрузить журнал аудита")).toBeInTheDocument();
  });

  it("детали JSON рендерятся безопасно (без выполнения разметки) и корректно обрабатывают null", async () => {
    vi.stubGlobal(
      "fetch",
      mockAuditApi([
        buildAuditRun({
          id: "audit-json",
          status: "success",
          input_json: { note: "<script>window.__pwned = true;</script>", document_id: "doc-1" },
          output_json: null,
        }),
      ]),
    );

    const { container } = renderPage();
    await screen.findByRole("table");

    // Both JSON blocks are present (input_json populated, output_json null).
    expect(screen.getByText("input_json")).toBeInTheDocument();
    expect(screen.getByText("output_json")).toBeInTheDocument();

    // No real <script> element was ever created from the JSON content.
    expect(container.querySelector("script")).toBeNull();

    const blocks = container.querySelectorAll("pre.json-block");
    const inputBlockText = Array.from(blocks)
      .map((el) => el.textContent ?? "")
      .find((text) => text.includes("note"));
    expect(inputBlockText).toContain("<script>window.__pwned = true;</script>");

    const outputBlockText = Array.from(blocks)
      .map((el) => el.textContent ?? "")
      .find((text) => text.trim() === "null");
    expect(outputBlockText).toBe("null");
  });

  it("stale-ответ при смене фильтра не перезаписывает актуальные данные", async () => {
    const deferred1 = createDeferred<Response>();
    const deferred2 = createDeferred<Response>();
    let callCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        assertAuditListRequest(input, init);
        callCount += 1;
        if (callCount === 1) return deferred1.promise;
        if (callCount === 2) return deferred2.promise;
        return Promise.reject(new Error("unexpected extra fetch call"));
      }),
    );

    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/загружаем журнал аудита/i);

    await user.selectOptions(screen.getByLabelText("Статус"), "error");

    // The newer (filtered) request resolves first.
    deferred2.resolve(jsonResponse(paginated([buildAuditRun({ id: "audit-err", status: "error" })])));
    await screen.findByRole("table");

    // The superseded initial request resolves late with different data.
    deferred1.resolve(jsonResponse(paginated([buildAuditRun({ id: "audit-ok", status: "success" })])));
    await flushMicrotasks();

    const table = screen.getByRole("table");
    expect(within(table).getByText("audit-err")).toBeInTheDocument();
    expect(within(table).queryByText("audit-ok")).not.toBeInTheDocument();
  });

  it("stale late error: устаревший запрос завершается ошибкой после успешного нового — актуальные данные остаются, banner не появляется", async () => {
    const deferred1 = createDeferred<Response>();
    const deferred2 = createDeferred<Response>();
    let callCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        assertAuditListRequest(input, init);
        callCount += 1;
        if (callCount === 1) return deferred1.promise;
        if (callCount === 2) return deferred2.promise;
        return Promise.reject(new Error("unexpected extra fetch call"));
      }),
    );

    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/загружаем журнал аудита/i);

    await user.selectOptions(screen.getByLabelText("Статус"), "error");

    deferred2.resolve(jsonResponse(paginated([buildAuditRun({ id: "audit-err", status: "error" })])));
    await screen.findByRole("table");

    deferred1.reject(new Error("boom: stale network failure"));
    await flushMicrotasks();

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("audit-err")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText("Не удалось загрузить журнал аудита")).not.toBeInTheDocument();
  });

  it("out-of-range: offset=20 и total упал до 15 -> коррекция на offset=0 и отображение первой страницы", async () => {
    let offsetZeroCalls = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = assertAuditListRequest(input, init);
      const offset = Number(url.searchParams.get("offset") ?? "0");
      if (offset === 20) {
        return Promise.resolve(jsonResponse(paginated([], { total: 15, limit: 20, offset: 20 })));
      }
      if (offset === 0) {
        offsetZeroCalls += 1;
        if (offsetZeroCalls === 1) {
          const items = Array.from({ length: 20 }, (_, i) => buildAuditRun({ id: `audit-${i}`, status: "success" }));
          return Promise.resolve(jsonResponse(paginated(items, { total: 25, limit: 20, offset: 0 })));
        }
        const items = Array.from({ length: 15 }, (_, i) => buildAuditRun({ id: `audit-${i}`, status: "success" }));
        return Promise.resolve(jsonResponse(paginated(items, { total: 15, limit: 20, offset: 0 })));
      }
      return Promise.reject(new Error(`unexpected offset: ${offset}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("table");

    await user.click(screen.getByRole("button", { name: "Далее" }));

    await screen.findByText(/показаны 1–15 из 15/i);
    const table = screen.getByRole("table");
    expect(within(table).getByText("audit-0")).toBeInTheDocument();
    expect(screen.queryByText("По заданному фильтру записи аудита не найдены.")).not.toBeInTheDocument();

    const offsetZeroRequests = fetchMock.mock.calls.filter(
      ([url]) => new URL(String(url)).searchParams.get("offset") === "0",
    );
    expect(offsetZeroRequests).toHaveLength(2); // initial load + corrected reload, no loop
  });

  it("out-of-range: offset=40, total=25 -> корректный новый offset=20", async () => {
    let offset20Calls = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = assertAuditListRequest(input, init);
      const offset = Number(url.searchParams.get("offset") ?? "0");
      const makeItems = (count: number, prefix: string) =>
        Array.from({ length: count }, (_, i) => buildAuditRun({ id: `${prefix}-${i}`, status: "success" }));

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
      const url = assertAuditListRequest(input, init);
      const offset = Number(url.searchParams.get("offset") ?? "0");
      if (offset === 0) {
        offsetZeroCalls += 1;
        if (offsetZeroCalls === 1) {
          const items = Array.from({ length: 20 }, (_, i) => buildAuditRun({ id: `audit-${i}`, status: "success" }));
          return Promise.resolve(jsonResponse(paginated(items, { total: 25, limit: 20, offset: 0 })));
        }
        return Promise.resolve(jsonResponse(paginated([], { total: 0, limit: 20, offset: 0 })));
      }
      return Promise.resolve(jsonResponse(paginated([], { total: 0, limit: 20, offset })));
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("table");

    await user.click(screen.getByRole("button", { name: "Далее" }));

    expect(await screen.findByText("По заданному фильтру записи аудита не найдены.")).toBeInTheDocument();
    expect(await screen.findByText("Нет записей")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});

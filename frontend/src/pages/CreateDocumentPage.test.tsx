import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { CreateDocumentPage } from "./CreateDocumentPage";
import { ReviewResultRoute } from "./ReviewResultPage";
import { getApiBaseUrl } from "../api/client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

/** Finds fetch calls by method + URL suffix instead of array position, so an
 * unrelated future fetch call (e.g. a new independent request added to a
 * page later) never breaks these assertions just by shifting call order. */
function findCalls(
  fetchMock: ReturnType<typeof vi.fn>,
  method: string,
  urlSuffix: string,
): Array<[unknown, RequestInit | undefined]> {
  return fetchMock.mock.calls.filter(([url, init]) => {
    const actualMethod = ((init as RequestInit | undefined)?.method ?? "GET").toUpperCase();
    return actualMethod === method.toUpperCase() && String(url).endsWith(urlSuffix);
  }) as Array<[unknown, RequestInit | undefined]>;
}

function findCall(
  fetchMock: ReturnType<typeof vi.fn>,
  method: string,
  urlSuffix: string,
): [unknown, RequestInit | undefined] | undefined {
  return findCalls(fetchMock, method, urlSuffix)[0];
}

/** Routes a stubbed `fetch` by method + URL suffix. Any request that matches
 * no route rejects loudly (instead of hanging on `undefined`), so a missing
 * mock branch fails the test rather than timing out. */
function routedFetch(
  routes: Array<{ method: string; urlSuffix: string; handler: () => Response | Promise<Response> }>,
) {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const route = routes.find((r) => r.method.toUpperCase() === method && url.endsWith(r.urlSuffix));
    if (route) return Promise.resolve(route.handler());
    return Promise.reject(new Error(`unexpected request: ${method} ${url}`));
  });
}

const DOCUMENT_TEXT =
  "Текст документа с достаточным количеством слов для прохождения проверки на бэкенде.";

const DOCUMENT_RESPONSE = {
  id: "doc-1",
  created_at: "2026-08-04T18:30:00Z",
  title: "Заголовок",
  text: DOCUMENT_TEXT,
  status: "created",
};

const REVIEW_RESPONSE = {
  id: "review-1",
  created_at: "2026-08-04T18:31:00Z",
  document_id: "doc-1",
  review_json: {
    summary: "Резюме проверки.",
    risks: [],
    missing_requirements: [],
    contradictions: [],
    questions_to_client: [],
    acceptance_criteria: [],
    confidence: "high",
    document_readiness: "ready",
    needs_review: false,
    review_reason_codes: [],
  },
  confidence: "high",
  readiness: "ready",
  needs_review: false,
  reason_codes: [],
  error: null,
};

async function fillForm(user: ReturnType<typeof userEvent.setup>, title = "Заголовок", text = DOCUMENT_TEXT) {
  await user.type(screen.getByLabelText(/название документа/i), title);
  await user.type(screen.getByLabelText(/текст документа/i), text);
}

describe("CreateDocumentPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("показывает актуальные бизнес-формулировки: заголовок, placeholder'ы, primary-кнопку", async () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <CreateDocumentPage />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("heading", { name: "ИИ-рецензент требований и технических заданий" }),
    ).toBeInTheDocument();

    const titleInput = screen.getByLabelText(/название документа/i) as HTMLInputElement;
    expect(titleInput.placeholder).toBe("Например: Требования к модулю уведомлений");

    // The task explicitly removed the narrow word "спецификация" from this
    // placeholder — regression-test the absence directly, not just the
    // presence of the new wording.
    const textArea = screen.getByLabelText(/текст документа/i) as HTMLTextAreaElement;
    expect(textArea.placeholder).toBe(
      "Вставьте техническое задание, требования, описание функции или задачи на автоматизацию…",
    );
    expect(textArea.placeholder.toLowerCase()).not.toContain("спецификац");

    expect(
      screen.getByRole("button", { name: "Сохранить документ и запустить проверку" }),
    ).toBeInTheDocument();
  });

  it("после создания документа показывает кнопку «Проверить другой документ»", async () => {
    const reviewDeferredResp = createDeferred<Response>();
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (method === "POST" && url.endsWith("/documents")) {
        return Promise.resolve(jsonResponse(DOCUMENT_RESPONSE, 201));
      }
      if (method === "POST" && url.endsWith("/documents/doc-1/review")) {
        return reviewDeferredResp.promise;
      }
      return Promise.reject(new Error(`unexpected request: ${method} ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <CreateDocumentPage />
      </MemoryRouter>,
    );

    await fillForm(user);
    await user.click(
      screen.getByRole("button", { name: /сохранить документ и запустить проверку/i }),
    );

    expect(
      await screen.findByRole("button", { name: "Проверить другой документ" }),
    ).toBeInTheDocument();

    // The pending review request is left unresolved intentionally: the
    // assertion above is the point of this test, and resolving it here would
    // trigger a post-test navigate() state update outside of `act(...)`.
  });

  it("не отправляет запрос, пока обязательные поля пусты", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <CreateDocumentPage />
      </MemoryRouter>,
    );

    const submitButton = screen.getByRole("button", {
      name: /сохранить документ и запустить проверку/i,
    });
    expect(submitButton).toBeDisabled();

    await user.click(submitButton);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("не отправляет запрос, если поля содержат только пробелы", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <MemoryRouter initialEntries={["/"]}>
        <CreateDocumentPage />
      </MemoryRouter>,
    );

    await user.type(screen.getByLabelText(/название документа/i), "   ");
    await user.type(screen.getByLabelText(/текст документа/i), "   ");

    const form = container.querySelector("form")!;
    fireEvent.submit(form);

    expect(fetch).not.toHaveBeenCalled();
  });

  it("отправляет создание документа с точным телом/методом/заголовками, затем точный запрос review", async () => {
    const fetchMock = routedFetch([
      { method: "POST", urlSuffix: "/documents", handler: () => jsonResponse(DOCUMENT_RESPONSE, 201) },
      {
        method: "POST",
        urlSuffix: "/documents/doc-1/review",
        handler: () => jsonResponse(REVIEW_RESPONSE, 201),
      },
    ]);
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <CreateDocumentPage />
      </MemoryRouter>,
    );

    await user.type(screen.getByLabelText(/название документа/i), "  Заголовок  ");
    await user.type(screen.getByLabelText(/текст документа/i), `  ${DOCUMENT_TEXT}  `);
    await user.click(
      screen.getByRole("button", { name: /сохранить документ и запустить проверку/i }),
    );

    await waitFor(() => expect(findCall(fetchMock, "POST", "/documents")).toBeDefined());
    const [createUrl, createInit] = findCall(fetchMock, "POST", "/documents")!;
    expect(String(createUrl)).toBe(`${getApiBaseUrl()}/documents`);
    expect((createInit?.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect(JSON.parse(createInit?.body as string)).toEqual({
      title: "Заголовок",
      text: DOCUMENT_TEXT,
    });

    await waitFor(() => expect(findCall(fetchMock, "POST", "/documents/doc-1/review")).toBeDefined());
    const [reviewUrl, reviewInit] = findCall(fetchMock, "POST", "/documents/doc-1/review")!;
    expect(String(reviewUrl)).toBe(`${getApiBaseUrl()}/documents/doc-1/review`);
    expect(reviewInit?.body).toBeUndefined();
  });

  it("не отправляет запрос review до завершения запроса создания документа", async () => {
    const createDeferredResp = createDeferred<Response>();
    const reviewDeferredResp = createDeferred<Response>();
    const callOrder: string[] = [];

    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (method === "POST" && url.endsWith("/documents")) {
        callOrder.push("create");
        return createDeferredResp.promise;
      }
      if (method === "POST" && url.endsWith("/documents/doc-1/review")) {
        callOrder.push("review");
        return reviewDeferredResp.promise;
      }
      return Promise.reject(new Error(`unexpected request: ${method} ${url}`));
    });

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <CreateDocumentPage />
      </MemoryRouter>,
    );

    await fillForm(user);
    await user.click(
      screen.getByRole("button", { name: /сохранить документ и запустить проверку/i }),
    );

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(callOrder).toEqual(["create"]);

    createDeferredResp.resolve(jsonResponse(DOCUMENT_RESPONSE, 201));
    await waitFor(() => expect(callOrder).toEqual(["create", "review"]));

    reviewDeferredResp.resolve(jsonResponse(REVIEW_RESPONSE, 201));
    await waitFor(() => expect(findCalls(fetchMock, "POST", "/documents/doc-1/review")).toHaveLength(1));
  });

  it("после успешного запуска переходит на страницу результата с точным reviewId", async () => {
    // Every branch is matched by method + URL, not call order/position — an
    // unrelated independent fetch added to the result page later (as
    // already happened once, with the source-document load) must not break
    // this test as long as this create → review → display contract holds.
    const fetchMock = routedFetch([
      { method: "POST", urlSuffix: "/documents", handler: () => jsonResponse(DOCUMENT_RESPONSE, 201) },
      {
        method: "POST",
        urlSuffix: "/documents/doc-1/review",
        handler: () => jsonResponse(REVIEW_RESPONSE, 201),
      },
      { method: "GET", urlSuffix: "/reviews/review-1", handler: () => jsonResponse(REVIEW_RESPONSE, 200) },
      { method: "GET", urlSuffix: "/documents/doc-1", handler: () => jsonResponse(DOCUMENT_RESPONSE, 200) },
    ]);
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<CreateDocumentPage />} />
          <Route path="/reviews/:reviewId" element={<ReviewResultRoute />} />
        </Routes>
      </MemoryRouter>,
    );

    await fillForm(user);
    await user.click(
      screen.getByRole("button", { name: /сохранить документ и запустить проверку/i }),
    );

    expect(
      await screen.findByRole("heading", { name: /результат проверки/i }),
    ).toBeInTheDocument();

    // The result page re-fetches the review by the exact reviewId from the
    // URL — proves navigation landed on the correct id, not just "some"
    // review route.
    await waitFor(() => expect(findCall(fetchMock, "GET", "/reviews/review-1")).toBeDefined());
    const [reviewGetUrl] = findCall(fetchMock, "GET", "/reviews/review-1")!;
    expect(String(reviewGetUrl)).toBe(`${getApiBaseUrl()}/reviews/${REVIEW_RESPONSE.id}`);

    // It also loads the source document by the review's own document_id.
    await waitFor(() => expect(findCall(fetchMock, "GET", "/documents/doc-1")).toBeDefined());
    const [documentGetUrl] = findCall(fetchMock, "GET", "/documents/doc-1")!;
    expect(String(documentGetUrl)).toBe(`${getApiBaseUrl()}/documents/${DOCUMENT_RESPONSE.id}`);
  });

  it("показывает пользователю русскоязычную ошибку при сбое создания документа", async () => {
    const fetchMock = routedFetch([
      {
        method: "POST",
        urlSuffix: "/documents",
        handler: () => jsonResponse({ detail: "Внутренняя ошибка сервера" }, 500),
      },
    ]);
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <CreateDocumentPage />
      </MemoryRouter>,
    );

    await fillForm(user);
    await user.click(
      screen.getByRole("button", { name: /сохранить документ и запустить проверку/i }),
    );

    expect(await screen.findByText("Внутренняя ошибка сервера")).toBeInTheDocument();
    expect(screen.getByText(/ошибка создания документа/i)).toBeInTheDocument();
    expect(findCalls(fetchMock, "POST", "/documents/doc-1/review")).toHaveLength(0);
  });

  it("не создаёт документ повторно и использует тот же id при повторном запуске review после ошибки", async () => {
    // Routed by exact method + URL rather than call order/position: a
    // per-endpoint counter decides the review endpoint's response (fail,
    // then succeed on retry), so an unrelated request can never accidentally
    // consume a response queued for a different endpoint the way a shared
    // `mockResolvedValueOnce` FIFO queue could.
    let createCalls = 0;
    let reviewCalls = 0;

    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();

      if (method === "POST" && url.endsWith("/documents")) {
        createCalls += 1;
        return Promise.resolve(jsonResponse(DOCUMENT_RESPONSE, 201));
      }

      if (method === "POST" && url.endsWith("/documents/doc-1/review")) {
        reviewCalls += 1;
        if (reviewCalls === 1) {
          return Promise.resolve(
            jsonResponse({ detail: "Не удалось выполнить проверку документа." }, 500),
          );
        }
        if (reviewCalls === 2) {
          return Promise.resolve(jsonResponse(REVIEW_RESPONSE, 201));
        }
        return Promise.reject(new Error(`unexpected extra review call #${reviewCalls}`));
      }

      if (method === "GET" && url.endsWith("/reviews/review-1")) {
        return Promise.resolve(jsonResponse(REVIEW_RESPONSE, 200));
      }

      if (method === "GET" && url.endsWith("/documents/doc-1")) {
        return Promise.resolve(jsonResponse(DOCUMENT_RESPONSE, 200));
      }

      return Promise.reject(new Error(`unexpected request: ${method} ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<CreateDocumentPage />} />
          <Route path="/reviews/:reviewId" element={<ReviewResultRoute />} />
        </Routes>
      </MemoryRouter>,
    );

    await fillForm(user);
    await user.click(
      screen.getByRole("button", { name: /сохранить документ и запустить проверку/i }),
    );

    expect(await screen.findByText("Не удалось выполнить проверку документа.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /повторить запуск проверки/i }));

    // The retry succeeds and navigates to the review id from the second attempt.
    expect(
      await screen.findByRole("heading", { name: /результат проверки/i }),
    ).toBeInTheDocument();

    expect(createCalls).toBe(1);
    expect(reviewCalls).toBe(2);

    // The document is created exactly once, regardless of the review retry.
    expect(findCalls(fetchMock, "POST", "/documents")).toHaveLength(1);

    // Both the failed attempt and the retry target the already-created
    // document's id, not a new/random/stale one, and neither sends a body.
    const reviewCallRecords = findCalls(fetchMock, "POST", "/documents/doc-1/review");
    expect(reviewCallRecords).toHaveLength(2);
    for (const [url, init] of reviewCallRecords) {
      expect(String(url)).toBe(`${getApiBaseUrl()}/documents/${DOCUMENT_RESPONSE.id}/review`);
      expect(init?.method).toBe("POST");
      expect(init?.body).toBeUndefined();
    }

    // The result page then re-fetches the review and the source document by
    // the exact ids from the successful retry — the earlier failed attempt
    // never leaked into navigation or these follow-up requests.
    const resultGetCall = findCall(fetchMock, "GET", "/reviews/review-1");
    expect(resultGetCall).toBeDefined();
    expect(String(resultGetCall![0])).toBe(`${getApiBaseUrl()}/reviews/${REVIEW_RESPONSE.id}`);

    const documentGetCall = findCall(fetchMock, "GET", "/documents/doc-1");
    expect(documentGetCall).toBeDefined();
    expect(String(documentGetCall![0])).toBe(`${getApiBaseUrl()}/documents/${DOCUMENT_RESPONSE.id}`);
  });
});

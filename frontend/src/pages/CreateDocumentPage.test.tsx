import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { CreateDocumentPage } from "./CreateDocumentPage";
import { ReviewResultPage } from "./ReviewResultPage";
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

  it("не отправляет запрос, пока обязательные поля пусты", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <CreateDocumentPage />
      </MemoryRouter>,
    );

    const submitButton = screen.getByRole("button", {
      name: /создать документ и запустить проверку/i,
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
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(jsonResponse(DOCUMENT_RESPONSE, 201))
      .mockResolvedValueOnce(jsonResponse(REVIEW_RESPONSE, 201));

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <CreateDocumentPage />
      </MemoryRouter>,
    );

    await user.type(screen.getByLabelText(/название документа/i), "  Заголовок  ");
    await user.type(screen.getByLabelText(/текст документа/i), `  ${DOCUMENT_TEXT}  `);
    await user.click(
      screen.getByRole("button", { name: /создать документ и запустить проверку/i }),
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    const [createUrl, createInit] = fetchMock.mock.calls[0];
    expect(String(createUrl)).toBe(`${getApiBaseUrl()}/documents`);
    expect(createInit?.method).toBe("POST");
    expect((createInit?.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect(JSON.parse(createInit?.body as string)).toEqual({
      title: "Заголовок",
      text: DOCUMENT_TEXT,
    });

    const [reviewUrl, reviewInit] = fetchMock.mock.calls[1];
    expect(String(reviewUrl)).toBe(`${getApiBaseUrl()}/documents/doc-1/review`);
    expect(reviewInit?.method).toBe("POST");
    expect(reviewInit?.body).toBeUndefined();
  });

  it("не отправляет запрос review до завершения запроса создания документа", async () => {
    const createDeferredResp = createDeferred<Response>();
    const reviewDeferredResp = createDeferred<Response>();
    const callOrder: string[] = [];

    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/documents")) {
        callOrder.push("create");
        return createDeferredResp.promise;
      }
      if (url.endsWith("/documents/doc-1/review")) {
        callOrder.push("review");
        return reviewDeferredResp.promise;
      }
      return Promise.reject(new Error(`unexpected url: ${url}`));
    });

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <CreateDocumentPage />
      </MemoryRouter>,
    );

    await fillForm(user);
    await user.click(
      screen.getByRole("button", { name: /создать документ и запустить проверку/i }),
    );

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(callOrder).toEqual(["create"]);

    createDeferredResp.resolve(jsonResponse(DOCUMENT_RESPONSE, 201));
    await waitFor(() => expect(callOrder).toEqual(["create", "review"]));

    reviewDeferredResp.resolve(jsonResponse(REVIEW_RESPONSE, 201));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it("после успешного запуска переходит на страницу результата с точным reviewId", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(jsonResponse(DOCUMENT_RESPONSE, 201))
      .mockResolvedValueOnce(jsonResponse(REVIEW_RESPONSE, 201))
      .mockResolvedValueOnce(jsonResponse(REVIEW_RESPONSE, 200));

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<CreateDocumentPage />} />
          <Route path="/reviews/:reviewId" element={<ReviewResultPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await fillForm(user);
    await user.click(
      screen.getByRole("button", { name: /создать документ и запустить проверку/i }),
    );

    expect(
      await screen.findByRole("heading", { name: /результат проверки/i }),
    ).toBeInTheDocument();

    // The result page re-fetches by reviewId from the URL: a 3rd call to the
    // exact `/reviews/{REVIEW_RESPONSE.id}` endpoint proves navigation landed
    // on the correct id, not just "some" review route.
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    const [thirdUrl] = fetchMock.mock.calls[2];
    expect(String(thirdUrl)).toBe(`${getApiBaseUrl()}/reviews/${REVIEW_RESPONSE.id}`);
  });

  it("показывает пользователю русскоязычную ошибку при сбое создания документа", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "Внутренняя ошибка сервера" }, 500));

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <CreateDocumentPage />
      </MemoryRouter>,
    );

    await fillForm(user);
    await user.click(
      screen.getByRole("button", { name: /создать документ и запустить проверку/i }),
    );

    expect(await screen.findByText("Внутренняя ошибка сервера")).toBeInTheDocument();
    expect(screen.getByText(/ошибка создания документа/i)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("не создаёт документ повторно и использует тот же id при повторном запуске review после ошибки", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(jsonResponse(DOCUMENT_RESPONSE, 201))
      .mockResolvedValueOnce(jsonResponse({ detail: "Не удалось выполнить проверку документа." }, 500))
      .mockResolvedValueOnce(jsonResponse(REVIEW_RESPONSE, 201));

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <CreateDocumentPage />
      </MemoryRouter>,
    );

    await fillForm(user);
    await user.click(
      screen.getByRole("button", { name: /создать документ и запустить проверку/i }),
    );

    expect(await screen.findByText("Не удалось выполнить проверку документа.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /повторить запуск проверки/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));

    const documentCreationCalls = fetchMock.mock.calls.filter(
      (call) => String(call[0]) === `${getApiBaseUrl()}/documents` && call[1]?.method === "POST",
    );
    expect(documentCreationCalls).toHaveLength(1);

    // The retried review call must target the already-created document's id,
    // not a new/random/stale one.
    const [thirdUrl, thirdInit] = fetchMock.mock.calls[2];
    expect(String(thirdUrl)).toBe(`${getApiBaseUrl()}/documents/${DOCUMENT_RESPONSE.id}/review`);
    expect(thirdInit?.method).toBe("POST");
  });
});

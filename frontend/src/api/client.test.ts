import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, getApiBaseUrl, isAbortError, request } from "./client";
import { parseDocumentResponse, parseReviewResponse } from "./validators";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function rawResponse(body: string, status = 200, contentType = "text/plain"): Response {
  return new Response(body, { status, headers: { "Content-Type": contentType } });
}

/** A duck-typed `Response` whose `.text()` rejects, simulating a
 * stream/network failure that happens *after* `fetch()` already resolved. */
function responseWithFailingBody(status: number, ok: boolean, rejection: unknown): Response {
  return { ok, status, text: () => Promise.reject(rejection) } as unknown as Response;
}

const VALID_DOCUMENT = {
  id: "doc-1",
  created_at: "2026-08-04T18:30:00Z",
  title: "Название",
  text: "Текст",
  status: "created",
};

describe("request", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("составляет endpoint URL из нормализованного базового адреса и пути", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse(VALID_DOCUMENT, 201));

    await request("/documents", { method: "POST" }, parseDocumentResponse);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toBe(`${getApiBaseUrl()}/documents`);
  });

  it("возвращает распарсенные и провалидированные данные при успешном ответе", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse(VALID_DOCUMENT, 201));

    const result = await request("/documents", { method: "POST" }, parseDocumentResponse);
    expect(result).toEqual(VALID_DOCUMENT);
  });

  it("бросает контролируемую ошибку при пустом теле успешного ответа", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(rawResponse("", 200));

    const error = await request("/reviews/1", undefined, parseDocumentResponse).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe(
      "Сервер вернул некорректный ответ. Повторите попытку или обратитесь к администратору.",
    );
  });

  it("бросает контролируемую ошибку при non-JSON успешном ответе", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(rawResponse("<html>not json</html>", 200, "text/html"));

    const error = await request("/reviews/1", undefined, parseDocumentResponse).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe(
      "Сервер вернул некорректный ответ. Повторите попытку или обратитесь к администратору.",
    );
    expect((error as ApiError).detail).toBeDefined();
  });

  it("не принимает null как валидный успешный ответ", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse(null, 200));

    const error = await request("/reviews/1", undefined, parseDocumentResponse).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe(
      "Сервер вернул некорректный ответ. Повторите попытку или обратитесь к администратору.",
    );
  });

  it("бросает контролируемую ошибку при структурно неверном JSON (не проходит валидатор)", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse({ unexpected: "shape" }, 200));

    const error = await request("/reviews/1", undefined, parseDocumentResponse).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe(
      "Сервер вернул некорректный ответ. Повторите попытку или обратитесь к администратору.",
    );
  });

  it("для 422 с type=uuid_parsing и loc review_id даёт русское сообщение без английского msg", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          detail: [
            {
              loc: ["path", "review_id"],
              msg: "Input should be a valid UUID, invalid character",
              type: "uuid_parsing",
            },
          ],
        },
        422,
      ),
    );

    const error = await request("/reviews/not-a-uuid", undefined, parseDocumentResponse).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe("Некорректный идентификатор проверки.");
    expect((error as ApiError).message).not.toMatch(/valid UUID/i);
    // Technical details (loc/type/original msg) stay available on the error object.
    expect((error as ApiError).detail).toMatchObject([{ type: "uuid_parsing" }]);
  });

  it("для 422 с type=uuid_parsing и loc document_id указывает документ", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        { detail: [{ loc: ["path", "document_id"], msg: "bad uuid", type: "uuid_parsing" }] },
        422,
      ),
    );

    const error = await request("/documents/not-a-uuid/review", undefined, parseDocumentResponse).catch(
      (e) => e,
    );
    expect((error as ApiError).message).toBe("Некорректный идентификатор документа.");
  });

  it("использует общий русскоязычный fallback для прочих 422 ошибок", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: [{ loc: ["body", "title"], msg: "field required", type: "missing" }] }, 422),
    );

    const error = await request("/documents", { method: "POST" }, parseDocumentResponse).catch((e) => e);
    expect((error as ApiError).message).toBe("Сервер отклонил данные запроса. Проверьте введённые значения.");
    expect((error as ApiError).message).not.toMatch(/field required/i);
  });

  it("пробрасывает AbortError без оборачивания в сетевую ошибку", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const abortError = new DOMException("Aborted", "AbortError");
    fetchMock.mockRejectedValueOnce(abortError);

    const error = await request("/documents", undefined, parseDocumentResponse).catch((e) => e);
    expect(isAbortError(error)).toBe(true);
    expect(error).not.toBeInstanceOf(ApiError);
  });

  it("оборачивает обычный сетевой сбой в русскоязычную ApiError", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    const error = await request("/documents", undefined, parseDocumentResponse).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).kind).toBe("network");
    expect((error as ApiError).message).toBe(
      "Не удалось соединиться с сервером. Проверьте подключение и адрес backend.",
    );
  });

  it("невалидное значение закрытого enum в успешном ответе -> ApiError(kind='invalid_response')", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse({ ...VALID_DOCUMENT, status: "pending" }, 201));

    const error = await request("/documents", undefined, parseDocumentResponse).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).kind).toBe("invalid_response");
    expect((error as ApiError).message).toBe(
      "Сервер вернул некорректный ответ. Повторите попытку или обратитесь к администратору.",
    );
  });

  it("ReviewResponse с расходящимся review_json (cross-field invariant) -> ApiError(kind='invalid_response')", async () => {
    const finalReview = {
      summary: "s",
      risks: [],
      missing_requirements: [],
      contradictions: [],
      questions_to_client: [],
      acceptance_criteria: [],
      confidence: "low",
      document_readiness: "not_ready",
      needs_review: false,
      review_reason_codes: [],
    };
    // Top-level confidence="high" disagrees with review_json.confidence="low" —
    // the whole response must be rejected, never silently reconciled.
    const mismatchedReview = {
      id: "review-1",
      created_at: "2026-08-04T18:30:00Z",
      document_id: "doc-1",
      review_json: finalReview,
      confidence: "high",
      readiness: "not_ready",
      needs_review: false,
      reason_codes: [],
      error: null,
    };
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse(mismatchedReview, 200));

    const error = await request("/reviews/review-1", undefined, parseReviewResponse).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).kind).toBe("invalid_response");
    expect((error as ApiError).message).toBe(
      "Сервер вернул некорректный ответ. Повторите попытку или обратитесь к администратору.",
    );
    // The underlying technical mismatch detail is preserved for logging, but
    // never surfaced as the user-facing message.
    expect(String((error as ApiError).detail)).toMatch(/confidence/);
  });

  // -------------------------------------------------------------------------
  // Malformed 422 validation-detail items: none of these have a trustworthy
  // `loc`/`type` shape, so `messageForValidationDetail` must fall back to the
  // generic message rather than throwing while reading `.loc.length` on
  // something that isn't actually an array.
  // -------------------------------------------------------------------------
  describe("malformed 422 validation detail", () => {
    const GENERIC = "Сервер отклонил данные запроса. Проверьте введённые значения.";

    it("uuid_type + корректный document_id -> сообщение про документ", async () => {
      const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
      fetchMock.mockResolvedValueOnce(
        jsonResponse({ detail: [{ loc: ["path", "document_id"], type: "uuid_type", msg: "bad" }] }, 422),
      );
      const error = await request("/documents/x/review", undefined, parseDocumentResponse).catch((e) => e);
      expect((error as ApiError).message).toBe("Некорректный идентификатор документа.");
    });

    it("отсутствующий loc -> общий fallback", async () => {
      const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
      fetchMock.mockResolvedValueOnce(jsonResponse({ detail: [{ type: "uuid_parsing", msg: "bad" }] }, 422));
      const error = await request("/reviews/x", undefined, parseDocumentResponse).catch((e) => e);
      expect((error as ApiError).message).toBe(GENERIC);
      expect((error as ApiError).detail).toMatchObject([{ type: "uuid_parsing" }]);
    });

    it("loc не является массивом -> общий fallback", async () => {
      const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
      fetchMock.mockResolvedValueOnce(
        jsonResponse({ detail: [{ loc: "review_id", type: "uuid_parsing", msg: "bad" }] }, 422),
      );
      const error = await request("/reviews/x", undefined, parseDocumentResponse).catch((e) => e);
      expect((error as ApiError).message).toBe(GENERIC);
    });

    it("item равен null -> общий fallback, без TypeError", async () => {
      const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
      fetchMock.mockResolvedValueOnce(jsonResponse({ detail: [null] }, 422));
      const error = await request("/reviews/x", undefined, parseDocumentResponse).catch((e) => e);
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).message).toBe(GENERIC);
    });

    it("item является строкой -> общий fallback, без TypeError", async () => {
      const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
      fetchMock.mockResolvedValueOnce(jsonResponse({ detail: ["oops"] }, 422));
      const error = await request("/reviews/x", undefined, parseDocumentResponse).catch((e) => e);
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).message).toBe(GENERIC);
    });

    it("неизвестный validation type -> общий fallback, без утечки msg", async () => {
      const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
      fetchMock.mockResolvedValueOnce(
        jsonResponse(
          { detail: [{ loc: ["body", "text"], type: "string_too_short", msg: "too short" }] },
          422,
        ),
      );
      const error = await request("/documents", { method: "POST" }, parseDocumentResponse).catch((e) => e);
      expect((error as ApiError).message).toBe(GENERIC);
      expect((error as ApiError).message).not.toMatch(/too short/i);
    });

    it("пустой массив detail -> общий fallback", async () => {
      const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
      fetchMock.mockResolvedValueOnce(jsonResponse({ detail: [] }, 422));
      const error = await request("/reviews/x", undefined, parseDocumentResponse).catch((e) => e);
      expect((error as ApiError).message).toBe(GENERIC);
    });

    it("malformed detail (объект вместо массива) -> общий fallback", async () => {
      const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
      fetchMock.mockResolvedValueOnce(jsonResponse({ detail: { unexpected: "shape" } }, 422));
      const error = await request("/reviews/x", undefined, parseDocumentResponse).catch((e) => e);
      expect((error as ApiError).message).toBe(GENERIC);
    });
  });

  // -------------------------------------------------------------------------
  // Non-JSON / empty bodies on an HTTP *error* status: the safe message must
  // come from the status code, never from the raw HTML/text body.
  // -------------------------------------------------------------------------
  describe("non-JSON HTTP error bodies", () => {
    it("500 с HTML телом -> безопасное сообщение по статусу, без утечки HTML", async () => {
      const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
      fetchMock.mockResolvedValueOnce(rawResponse("<html><body>boom</body></html>", 500, "text/html"));
      const error = await request("/documents", undefined, parseDocumentResponse).catch((e) => e);
      expect((error as ApiError).message).toBe(
        "Внутренняя ошибка сервера. Попробуйте повторить запрос позже.",
      );
      expect((error as ApiError).message).not.toMatch(/<html>/i);
    });

    it("500 с plain text телом -> безопасное сообщение по статусу", async () => {
      const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
      fetchMock.mockResolvedValueOnce(rawResponse("internal server panic", 500, "text/plain"));
      const error = await request("/documents", undefined, parseDocumentResponse).catch((e) => e);
      expect((error as ApiError).message).toBe(
        "Внутренняя ошибка сервера. Попробуйте повторить запрос позже.",
      );
      expect((error as ApiError).message).not.toMatch(/panic/i);
    });

    it("404 с пустым телом -> «Запрошенные данные не найдены.»", async () => {
      const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
      fetchMock.mockResolvedValueOnce(rawResponse("", 404));
      const error = await request("/reviews/missing", undefined, parseDocumentResponse).catch((e) => e);
      expect((error as ApiError).message).toBe("Запрошенные данные не найдены.");
    });

    it("malformed JSON при статусе ошибки -> безопасное сообщение по статусу", async () => {
      const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
      fetchMock.mockResolvedValueOnce(rawResponse("{not valid json", 500, "application/json"));
      const error = await request("/documents", undefined, parseDocumentResponse).catch((e) => e);
      expect((error as ApiError).message).toBe(
        "Внутренняя ошибка сервера. Попробуйте повторить запрос позже.",
      );
    });
  });

  // -------------------------------------------------------------------------
  // response.text() itself failing (stream/network error after a successful
  // fetch()), for both a 2xx and an error status, plus the abort variant.
  // -------------------------------------------------------------------------
  describe("response body read failures", () => {
    it("сбой чтения тела при успешном статусе -> контролируемая ApiError", async () => {
      const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
      const streamError = new Error("stream interrupted");
      fetchMock.mockResolvedValueOnce(responseWithFailingBody(200, true, streamError));

      const error = await request("/documents", undefined, parseDocumentResponse).catch((e) => e);
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).kind).toBe("network");
      expect((error as ApiError).message).toBe(
        "Не удалось получить ответ сервера. Проверьте подключение и повторите попытку.",
      );
      expect((error as ApiError).detail).toBe(streamError);
      expect((error as ApiError).message).not.toMatch(/stream interrupted/i);
    });

    it("сбой чтения тела при статусе ошибки -> контролируемая ApiError", async () => {
      const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
      const streamError = new Error("stream interrupted");
      fetchMock.mockResolvedValueOnce(responseWithFailingBody(500, false, streamError));

      const error = await request("/documents", undefined, parseDocumentResponse).catch((e) => e);
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).kind).toBe("network");
      expect((error as ApiError).message).toBe(
        "Не удалось получить ответ сервера. Проверьте подключение и повторите попытку.",
      );
    });

    it("abort во время чтения тела остаётся abort, а не пользовательской ошибкой", async () => {
      const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
      const abortError = new DOMException("Aborted", "AbortError");
      fetchMock.mockResolvedValueOnce(responseWithFailingBody(200, true, abortError));

      const error = await request("/documents", undefined, parseDocumentResponse).catch((e) => e);
      expect(isAbortError(error)).toBe(true);
      expect(error).not.toBeInstanceOf(ApiError);
    });
  });

  // -------------------------------------------------------------------------
  // VITE_API_BASE_URL configuration errors: caught before any fetch call and
  // turned into a safe Russian message, never a raw stack trace.
  // -------------------------------------------------------------------------
  describe("base URL configuration errors", () => {
    it("некорректный VITE_API_BASE_URL -> ApiError(kind='config') без fetch", async () => {
      vi.stubEnv("VITE_API_BASE_URL", "http://host:8000/backend");
      const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;

      const error = await request("/documents", undefined, parseDocumentResponse).catch((e) => e);

      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).kind).toBe("config");
      expect((error as ApiError).message).toBe("Некорректно настроен адрес API.");
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it("VITE_API_BASE_URL с query string -> ApiError(kind='config')", async () => {
      vi.stubEnv("VITE_API_BASE_URL", "http://host:8000/api?x=1");

      const error = await request("/documents", undefined, parseDocumentResponse).catch((e) => e);

      expect((error as ApiError).kind).toBe("config");
      expect((error as ApiError).message).toBe("Некорректно настроен адрес API.");
    });
  });
});

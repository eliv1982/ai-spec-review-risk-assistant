import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { exportReviewCsv, exportReviewsCsv } from "./reviews";
import { ApiError, getApiBaseUrl } from "./client";

const REVIEWS_URL = new URL(`${getApiBaseUrl()}/reviews`);
const ORIGIN = REVIEWS_URL.origin;

function csvResponse(body: string, headers: Record<string, string> = {}, status = 200): Response {
  return new Response(body, {
    status,
    headers: { "Content-Type": "text/csv; charset=utf-8", ...headers },
  });
}

function jsonErrorResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Node's fetch can return a Blob from a different realm than jsdom's global
 * Blob. Prefer the Blob's own reader when available; older jsdom Blobs need
 * FileReader instead. */
function readBlobAsText(blob: Blob): Promise<string> {
  if (typeof blob.text === "function") {
    return blob.text();
  }

  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(blob);
  });
}

describe("exportReviewsCsv", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("отправляет точный запрос GET /api/reviews/export без фильтров и без пагинации", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      csvResponse("data", { "Content-Disposition": 'attachment; filename="reviews-export.csv"' }),
    );

    await exportReviewsCsv({});

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect((init?.method ?? "GET")).toBe("GET");
    expect(String(url)).toBe(`${ORIGIN}/api/reviews/export`);
  });

  it("включает document_id/needs_review/confidence/readiness как query параметры", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(csvResponse("data"));

    await exportReviewsCsv({
      documentId: "doc-1",
      needsReview: true,
      confidence: "low",
      readiness: "not_ready",
    });

    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(String(url));
    expect(parsed.searchParams.get("document_id")).toBe("doc-1");
    expect(parsed.searchParams.get("needs_review")).toBe("true");
    expect(parsed.searchParams.get("confidence")).toBe("low");
    expect(parsed.searchParams.get("readiness")).toBe("not_ready");
    expect(parsed.searchParams.has("limit")).toBe(false);
    expect(parsed.searchParams.has("offset")).toBe(false);
  });

  it("не добавляет пустые query параметры при отсутствии фильтров", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(csvResponse("data"));

    await exportReviewsCsv({});

    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toBe(`${ORIGIN}/api/reviews/export`);
  });

  it("возвращает CSV Blob и извлекает filename из Content-Disposition", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      csvResponse("a;b\r\n1;2\r\n", {
        "Content-Disposition": 'attachment; filename="reviews-export.csv"',
      }),
    );

    const result = await exportReviewsCsv({});
    expect(await readBlobAsText(result.blob)).toBe("a;b\r\n1;2\r\n");
    expect(result.blob.type.toLowerCase().replace(/\s/g, "")).toBe("text/csv;charset=utf-8");
    expect(result.filename).toBe("reviews-export.csv");
  });

  it("использует fallback filename при отсутствующем заголовке Content-Disposition", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(csvResponse("data"));

    const result = await exportReviewsCsv({});
    expect(result.filename).toBe("reviews-export.csv");
  });

  it("использует fallback filename при повреждённом заголовке Content-Disposition", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(csvResponse("data", { "Content-Disposition": "attachment" }));

    const result = await exportReviewsCsv({});
    expect(result.filename).toBe("reviews-export.csv");
  });

  it("санитизирует path traversal в имени файла из заголовка", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      csvResponse("data", { "Content-Disposition": 'attachment; filename="../../etc/passwd"' }),
    );

    const result = await exportReviewsCsv({});
    expect(result.filename).not.toContain("/");
    expect(result.filename).not.toContain("\\");
  });

  it("выбрасывает ApiError при не-2xx ответе", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonErrorResponse({ detail: "Внутренняя ошибка сервера" }, 500));

    const error = await exportReviewsCsv({}).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe("Внутренняя ошибка сервера");
  });
});

describe("exportReviewCsv", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("отправляет точный запрос GET /api/reviews/{review_id}/export", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(csvResponse("data"));

    await exportReviewCsv("review-123");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect((init?.method ?? "GET")).toBe("GET");
    expect(String(url)).toBe(`${ORIGIN}/api/reviews/review-123/export`);
  });

  it("использует fallback filename review-{id}.csv при отсутствующем заголовке", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(csvResponse("data"));

    const result = await exportReviewCsv("review-123");
    expect(result.filename).toBe("review-review-123.csv");
  });

  it("возвращает Blob и точный review id в пути даже при спецсимволах", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(csvResponse("data"));

    await exportReviewCsv("id with space");

    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toBe(`${ORIGIN}/api/reviews/${encodeURIComponent("id with space")}/export`);
  });

  it("выбрасывает ApiError при 404", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonErrorResponse({ detail: "Проверка не найдена" }, 404));

    const error = await exportReviewCsv("missing").catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(404);
  });

  it("санитизирует опасный review_id внутри сгенерированного fallback filename при отсутствующем заголовке", async () => {
    // The fallback filename is built as `review-${reviewId}.csv` — if the
    // review id itself contained a path separator, that separator must not
    // survive into the fallback filename used for a missing/unparseable
    // Content-Disposition header.
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(csvResponse("data"));

    const result = await exportReviewCsv("../../etc/passwd");
    expect(result.filename).not.toContain("/");
    expect(result.filename).not.toContain("\\");
    expect(result.filename.length).toBeGreaterThan(0);
  });
});

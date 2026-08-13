import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { exportAuditRunsCsv } from "./audit";
import { ApiError, getApiBaseUrl } from "./client";

const AUDIT_URL = new URL(`${getApiBaseUrl()}/audit-runs`);
const ORIGIN = AUDIT_URL.origin;

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

describe("exportAuditRunsCsv", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("отправляет точный запрос GET /api/audit-runs/export без фильтров и без пагинации", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(csvResponse("data"));

    await exportAuditRunsCsv({});

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect((init?.method ?? "GET")).toBe("GET");
    expect(String(url)).toBe(`${ORIGIN}/api/audit-runs/export`);
  });

  it("включает status как query параметр", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(csvResponse("data"));

    await exportAuditRunsCsv({ status: "success" });

    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(String(url));
    expect(parsed.searchParams.get("status")).toBe("success");
    expect(parsed.searchParams.has("errors_only")).toBe(false);
    expect(parsed.searchParams.has("limit")).toBe(false);
    expect(parsed.searchParams.has("offset")).toBe(false);
  });

  it("включает errors_only=true и никогда одновременно со status", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(csvResponse("data"));

    await exportAuditRunsCsv({ errorsOnly: true });

    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(String(url));
    expect(parsed.searchParams.get("errors_only")).toBe("true");
    expect(parsed.searchParams.has("status")).toBe(false);
  });

  it("не добавляет пустые query параметры при отсутствии фильтров", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(csvResponse("data"));

    await exportAuditRunsCsv({});

    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toBe(`${ORIGIN}/api/audit-runs/export`);
  });

  it("возвращает CSV Blob и извлекает filename из Content-Disposition", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      csvResponse("a;b\r\n1;2\r\n", {
        "Content-Disposition": 'attachment; filename="audit-runs-export.csv"',
      }),
    );

    const result = await exportAuditRunsCsv({});
    expect(await readBlobAsText(result.blob)).toBe("a;b\r\n1;2\r\n");
    expect(result.blob.type.toLowerCase().replace(/\s/g, "")).toBe("text/csv;charset=utf-8");
    expect(result.filename).toBe("audit-runs-export.csv");
  });

  it("использует fallback filename при отсутствующем заголовке Content-Disposition", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(csvResponse("data"));

    const result = await exportAuditRunsCsv({});
    expect(result.filename).toBe("audit-runs-export.csv");
  });

  it("использует fallback filename при повреждённом заголовке Content-Disposition", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(csvResponse("data", { "Content-Disposition": "attachment" }));

    const result = await exportAuditRunsCsv({});
    expect(result.filename).toBe("audit-runs-export.csv");
  });

  it("санитизирует path traversal в имени файла из заголовка", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      csvResponse("data", { "Content-Disposition": 'attachment; filename="../../etc/passwd"' }),
    );

    const result = await exportAuditRunsCsv({});
    expect(result.filename).not.toContain("/");
    expect(result.filename).not.toContain("\\");
  });

  it("выбрасывает ApiError при не-2xx ответе", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonErrorResponse({ detail: "Внутренняя ошибка сервера" }, 500));

    const error = await exportAuditRunsCsv({}).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe("Внутренняя ошибка сервера");
  });
});

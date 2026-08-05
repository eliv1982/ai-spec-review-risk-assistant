import { describe, expect, it } from "vitest";
import { ApiBaseUrlConfigError, normalizeApiBaseUrl } from "./baseUrl";

describe("normalizeApiBaseUrl — supported values", () => {
  it.each([
    ["http://host:8000", "http://host:8000/api"],
    ["http://host:8000/", "http://host:8000/api"],
    ["http://host:8000///", "http://host:8000/api"],
    ["http://host:8000/api", "http://host:8000/api"],
    ["http://host:8000/api/", "http://host:8000/api"],
    ["http://host:8000/api//", "http://host:8000/api"],
    ["http://host:8000/api/api", "http://host:8000/api"],
    ["http://host:8000/api/api/", "http://host:8000/api"],
    ["http://host:8000/api/api//", "http://host:8000/api"],
  ])("нормализует %s в %s", (input, expected) => {
    expect(normalizeApiBaseUrl(input)).toBe(expected);
  });

  it("тест «не создаёт /api/api» реально подаёт /api/api на входе", () => {
    expect(normalizeApiBaseUrl("http://host:8000/api/api")).toBe("http://host:8000/api");
    expect(normalizeApiBaseUrl("http://host:8000/api/api")).not.toBe("http://host:8000/api/api");
  });

  it("не изменяет hostname, содержащий подстроку api", () => {
    expect(normalizeApiBaseUrl("http://api-host.example:8000")).toBe(
      "http://api-host.example:8000/api",
    );
  });

  it("использует безопасный default, когда переменная не задана", () => {
    expect(normalizeApiBaseUrl(undefined)).toBe("http://127.0.0.1:8000/api");
    expect(normalizeApiBaseUrl(null)).toBe("http://127.0.0.1:8000/api");
    expect(normalizeApiBaseUrl("")).toBe("http://127.0.0.1:8000/api");
    expect(normalizeApiBaseUrl("   ")).toBe("http://127.0.0.1:8000/api");
  });

  it("обрезает пробелы вокруг значения", () => {
    expect(normalizeApiBaseUrl("  http://host:9000/api  ")).toBe("http://host:9000/api");
  });

  it("возвращает ожидаемый endpoint URL при склейке с путём", () => {
    expect(`${normalizeApiBaseUrl("http://host:8000/api//")}/documents`).toBe(
      "http://host:8000/api/documents",
    );
    expect(`${normalizeApiBaseUrl("http://host:8000")}/reviews/abc-123`).toBe(
      "http://host:8000/api/reviews/abc-123",
    );
  });
});

describe("normalizeApiBaseUrl — rejected as configuration error", () => {
  it.each([
    ["http://host:8000/api?x=1", "query string"],
    ["http://host:8000/api#section", "fragment"],
    ["http://host:8000/backend", "unsupported pathname"],
    ["http://host:8000/v1", "unsupported pathname"],
    ["http://host:8000/backend/api", "unsupported pathname (mixed)"],
    ["/api", "relative URL"],
    ["not-a-url", "not a URL at all"],
    ["ftp://host:8000/api", "unsupported protocol"],
  ])("отклоняет %s (%s) как ApiBaseUrlConfigError", (input) => {
    expect(() => normalizeApiBaseUrl(input)).toThrow(ApiBaseUrlConfigError);
  });

  it("не превращает query string в некорректный склеенный URL", () => {
    expect(() => normalizeApiBaseUrl("http://host:8000/api?x=1")).toThrow();
    // Explicitly not accepted as a valid base — never silently becomes
    // ".../api?x=1/api" or similar.
  });

  it("сохраняет исходное значение в ApiBaseUrlConfigError.rawValue", () => {
    try {
      normalizeApiBaseUrl("http://host:8000/backend");
      throw new Error("expected normalizeApiBaseUrl to throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiBaseUrlConfigError);
      expect((err as ApiBaseUrlConfigError).rawValue).toBe("http://host:8000/backend");
    }
  });
});

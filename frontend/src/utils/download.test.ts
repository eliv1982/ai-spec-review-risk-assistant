import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { downloadBlob, extractContentDispositionFilename, sanitizeFilename } from "./download";

describe("extractContentDispositionFilename", () => {
  it("извлекает filename из заголовка в кавычках", () => {
    expect(extractContentDispositionFilename('attachment; filename="reviews-export.csv"')).toBe(
      "reviews-export.csv",
    );
  });

  it("извлекает filename без кавычек", () => {
    expect(extractContentDispositionFilename("attachment; filename=audit-runs-export.csv")).toBe(
      "audit-runs-export.csv",
    );
  });

  it("возвращает null при отсутствующем заголовке", () => {
    expect(extractContentDispositionFilename(null)).toBeNull();
  });

  it("возвращает null при заголовке без параметра filename", () => {
    expect(extractContentDispositionFilename("attachment")).toBeNull();
  });

  it("возвращает null при пустой строке заголовка", () => {
    expect(extractContentDispositionFilename("")).toBeNull();
  });
});

describe("sanitizeFilename", () => {
  it("оставляет безопасное имя без изменений", () => {
    expect(sanitizeFilename("reviews-export.csv")).toBe("reviews-export.csv");
  });

  it("удаляет прямые слэши", () => {
    expect(sanitizeFilename("a/b/c.csv")).toBe("abc.csv");
  });

  it("удаляет обратные слэши", () => {
    expect(sanitizeFilename("a\\b\\c.csv")).toBe("abc.csv");
  });

  it("удаляет управляющие символы", () => {
    expect(sanitizeFilename("a\u0000b\u001fc\u007fd.csv")).toBe("abcd.csv");
  });

  it("нейтрализует path traversal — после удаления слэшей нет ссылки на родительский каталог", () => {
    const result = sanitizeFilename("../../etc/passwd");
    expect(result).not.toContain("/");
    expect(result).not.toContain("\\");
  });

  it("использует fallback при пустой строке", () => {
    expect(sanitizeFilename("", "fallback.csv")).toBe("fallback.csv");
  });

  it("использует fallback, если после очистки остались только слэши", () => {
    expect(sanitizeFilename("///", "fallback.csv")).toBe("fallback.csv");
  });

  it("использует fallback, если имя состоит только из точек", () => {
    expect(sanitizeFilename("...", "fallback.csv")).toBe("fallback.csv");
  });

  it("использует значение по умолчанию export.csv, если fallback не передан", () => {
    expect(sanitizeFilename("")).toBe("export.csv");
  });
});

describe("downloadBlob", () => {
  let createObjectURLMock: ReturnType<typeof vi.fn>;
  let revokeObjectURLMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    createObjectURLMock = vi.fn(() => "blob:mock-url");
    revokeObjectURLMock = vi.fn();
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: createObjectURLMock,
      revokeObjectURL: revokeObjectURLMock,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("создаёт object URL, кликает по временной ссылке и удаляет её, затем освобождает URL", () => {
    const blob = new Blob(["a;b\r\n"], { type: "text/csv" });
    const realCreateElement = document.createElement.bind(document);
    const appendSpy = vi.spyOn(document.body, "appendChild");
    const removeSpy = vi.spyOn(document.body, "removeChild");

    let clicked = false;
    const createElementSpy = vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = realCreateElement(tag);
      if (tag === "a") {
        (el as HTMLAnchorElement).click = () => {
          clicked = true;
        };
      }
      return el;
    });

    downloadBlob(blob, "reviews-export.csv");

    expect(createObjectURLMock).toHaveBeenCalledWith(blob);
    expect(createElementSpy).toHaveBeenCalledWith("a");
    expect(appendSpy).toHaveBeenCalledTimes(1);
    const anchor = appendSpy.mock.calls[0][0] as HTMLAnchorElement;
    expect(anchor.getAttribute("download")).toBe("reviews-export.csv");
    expect(anchor.href).toContain("blob:mock-url");
    expect(clicked).toBe(true);
    expect(removeSpy).toHaveBeenCalledWith(anchor);
    expect(revokeObjectURLMock).toHaveBeenCalledWith("blob:mock-url");

    appendSpy.mockRestore();
    removeSpy.mockRestore();
    createElementSpy.mockRestore();
  });

  it("освобождает object URL и удаляет ссылку, даже если click() выбрасывает исключение", () => {
    const blob = new Blob(["a;b\r\n"], { type: "text/csv" });
    const realCreateElement = document.createElement.bind(document);
    const removeSpy = vi.spyOn(document.body, "removeChild");
    const createElementSpy = vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = realCreateElement(tag);
      if (tag === "a") {
        (el as HTMLAnchorElement).click = () => {
          throw new Error("click failed");
        };
      }
      return el;
    });

    expect(() => downloadBlob(blob, "reviews-export.csv")).toThrow("click failed");

    expect(removeSpy).toHaveBeenCalledTimes(1);
    expect(revokeObjectURLMock).toHaveBeenCalledTimes(1);
    expect(revokeObjectURLMock).toHaveBeenCalledWith("blob:mock-url");

    removeSpy.mockRestore();
    createElementSpy.mockRestore();
  });

  it("освобождает object URL, если document.createElement выбрасывает исключение, и не пытается удалить anchor", () => {
    const blob = new Blob(["a;b\r\n"], { type: "text/csv" });
    const removeSpy = vi.spyOn(document.body, "removeChild");
    const createElementSpy = vi.spyOn(document, "createElement").mockImplementation(() => {
      throw new Error("createElement failed");
    });

    expect(() => downloadBlob(blob, "reviews-export.csv")).toThrow("createElement failed");

    expect(removeSpy).not.toHaveBeenCalled();
    expect(revokeObjectURLMock).toHaveBeenCalledTimes(1);
    expect(revokeObjectURLMock).toHaveBeenCalledWith("blob:mock-url");

    removeSpy.mockRestore();
    createElementSpy.mockRestore();
  });

  it("освобождает object URL, если appendChild выбрасывает исключение, и не пытается удалить anchor", () => {
    const blob = new Blob(["a;b\r\n"], { type: "text/csv" });
    const appendSpy = vi.spyOn(document.body, "appendChild").mockImplementation(() => {
      throw new Error("appendChild failed");
    });
    const removeSpy = vi.spyOn(document.body, "removeChild");

    expect(() => downloadBlob(blob, "reviews-export.csv")).toThrow("appendChild failed");

    expect(removeSpy).not.toHaveBeenCalled();
    expect(revokeObjectURLMock).toHaveBeenCalledTimes(1);
    expect(revokeObjectURLMock).toHaveBeenCalledWith("blob:mock-url");

    appendSpy.mockRestore();
    removeSpy.mockRestore();
  });

  it("освобождает object URL ровно один раз, даже если removeChild выбрасывает исключение", () => {
    const blob = new Blob(["a;b\r\n"], { type: "text/csv" });
    const realCreateElement = document.createElement.bind(document);
    const createElementSpy = vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = realCreateElement(tag);
      if (tag === "a") {
        (el as HTMLAnchorElement).click = () => {};
      }
      return el;
    });
    const removeSpy = vi.spyOn(document.body, "removeChild").mockImplementation(() => {
      throw new Error("removeChild failed");
    });

    expect(() => downloadBlob(blob, "reviews-export.csv")).toThrow("removeChild failed");

    expect(revokeObjectURLMock).toHaveBeenCalledTimes(1);
    expect(revokeObjectURLMock).toHaveBeenCalledWith("blob:mock-url");

    removeSpy.mockRestore();
    createElementSpy.mockRestore();
  });

  it("освобождает object URL ровно один раз при обычном успешном скачивании", () => {
    const blob = new Blob(["a;b\r\n"], { type: "text/csv" });
    const realCreateElement = document.createElement.bind(document);
    const createElementSpy = vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = realCreateElement(tag);
      if (tag === "a") {
        (el as HTMLAnchorElement).click = () => {};
      }
      return el;
    });

    downloadBlob(blob, "reviews-export.csv");

    expect(revokeObjectURLMock).toHaveBeenCalledTimes(1);

    createElementSpy.mockRestore();
  });
});

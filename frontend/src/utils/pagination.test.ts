import { describe, expect, it } from "vitest";
import { computeCorrectedOffset } from "./pagination";

describe("computeCorrectedOffset", () => {
  it("offset=20, total=15 (сократился до <= offset) -> корректирует на 0", () => {
    expect(computeCorrectedOffset({ itemCount: 0, offset: 20, total: 15, pageSize: 20 })).toBe(0);
  });

  it("offset=40, total=25 -> корректирует на 20 (последняя валидная страница)", () => {
    expect(computeCorrectedOffset({ itemCount: 0, offset: 40, total: 25, pageSize: 20 })).toBe(20);
  });

  it("total=0 и offset>0 -> корректирует на 0", () => {
    expect(computeCorrectedOffset({ itemCount: 0, offset: 20, total: 0, pageSize: 20 })).toBe(0);
  });

  it("total=0 и offset уже 0 -> не требует коррекции (обычное пустое состояние)", () => {
    expect(computeCorrectedOffset({ itemCount: 0, offset: 0, total: 0, pageSize: 20 })).toBeNull();
  });

  it("offset=0 (первая страница) -> никогда не корректирует, даже если items пуст", () => {
    expect(computeCorrectedOffset({ itemCount: 0, offset: 0, total: 5, pageSize: 20 })).toBeNull();
  });

  it("items не пуст -> не корректирует, даже если offset >= total (защитная проверка)", () => {
    expect(computeCorrectedOffset({ itemCount: 3, offset: 20, total: 15, pageSize: 20 })).toBeNull();
  });

  it("offset < total -> страница валидна, коррекция не требуется", () => {
    expect(computeCorrectedOffset({ itemCount: 0, offset: 10, total: 25, pageSize: 20 })).toBeNull();
  });

  it("не создаёт бесконечный цикл: повторное применение сразу даёt null (страница стабильна)", () => {
    const first = computeCorrectedOffset({ itemCount: 0, offset: 40, total: 25, pageSize: 20 });
    expect(first).toBe(20);
    // At the corrected offset, the same total now yields a valid (non-empty in practice) page.
    const second = computeCorrectedOffset({ itemCount: 5, offset: first!, total: 25, pageSize: 20 });
    expect(second).toBeNull();
  });

  it.each([
    { offset: 100, total: 99, pageSize: 20 },
    { offset: 21, total: 1, pageSize: 20 },
    { offset: 1000, total: 1, pageSize: 50 },
  ])("корректированное значение всегда строго меньше текущего offset: %j", ({ offset, total, pageSize }) => {
    const corrected = computeCorrectedOffset({ itemCount: 0, offset, total, pageSize });
    expect(corrected).not.toBeNull();
    expect(corrected!).toBeLessThan(offset);
  });
});

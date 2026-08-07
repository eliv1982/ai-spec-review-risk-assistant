import { describe, expect, it } from "vitest";
import { formatDateTime, formatDuration } from "./formatting";

describe("formatDateTime", () => {
  it("converts a UTC ISO timestamp to DD.MM.YYYY, HH:MM in Moscow time", () => {
    expect(formatDateTime("2026-08-07T06:32:07Z")).toBe("07.08.2026, 09:32");
  });

  it("crosses a day boundary correctly", () => {
    expect(formatDateTime("2026-08-07T22:15:00Z")).toBe("08.08.2026, 01:15");
  });

  it("falls back to the raw value when it cannot be parsed", () => {
    expect(formatDateTime("not-a-real-timestamp")).toBe("not-a-real-timestamp");
  });
});

describe("formatDuration", () => {
  it("keeps short durations in milliseconds", () => {
    expect(formatDuration(5)).toBe("5 мс");
    expect(formatDuration(14)).toBe("14 мс");
    expect(formatDuration(999)).toBe("999 мс");
    expect(formatDuration(0)).toBe("0 мс");
  });

  it("switches to seconds at the one-second boundary", () => {
    expect(formatDuration(1000)).toBe("1,0 с");
  });

  it("rounds to one decimal with a Russian comma separator", () => {
    expect(formatDuration(36950)).toBe("37,0 с");
  });

  it("rounds half up", () => {
    // 1250 ms -> 12.5 tenths of a second -> rounds up to 13 (1.3s), matching
    // the backend's floor(x + 0.5) equivalent rather than banker's rounding.
    expect(formatDuration(1250)).toBe("1,3 с");
  });
});

/** Deterministic Russian datetime/duration display formatting, shared by
 * every page that renders a backend `created_at` (canonical UTC ISO 8601,
 * e.g. `"2026-08-07T06:32:07Z"`) or `duration_ms` value. Fixed to
 * Europe/Moscow (via `Intl.DateTimeFormat`'s `timeZone` option, which does
 * not depend on the viewer's own browser locale/timezone) so the rendered
 * text is deterministic across machines instead of drifting with the
 * viewer's local timezone — matching the backend's equivalent
 * `format_datetime_ru`/`format_duration_ru` (app/services/display_labels.py). */

const DATE_TIME_FORMATTER = new Intl.DateTimeFormat("ru-RU", {
  timeZone: "Europe/Moscow",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

/** Formats a canonical UTC ISO 8601 string as `"07.08.2026, 09:32"`
 * (DD.MM.YYYY, HH:MM in Moscow local time). Falls back to the raw value
 * unchanged if it cannot be parsed, so a malformed value never crashes the
 * page. */
export function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return DATE_TIME_FORMATTER.format(date);
}

/** Formats a millisecond duration for display: durations under one second
 * stay in milliseconds (`"14 мс"`); one second and above switch to a
 * one-decimal seconds value with a Russian comma separator (`"37,0 с"`).
 * Rounds half up (`Math.round`), matching the equivalent backend helper. */
export function formatDuration(durationMs: number): string {
  if (durationMs < 1000) return `${durationMs} мс`;
  const tenths = Math.round(durationMs / 100);
  const seconds = (tenths / 10).toFixed(1).replace(".", ",");
  return `${seconds} с`;
}

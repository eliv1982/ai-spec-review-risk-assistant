interface JsonBlockProps {
  title: string;
  value: unknown;
  defaultOpen?: boolean;
}

/** Formats `value` as indented JSON text. Never throws: a value that cannot
 * be serialized (or a malformed historical row) falls back to a safe,
 * literal placeholder instead of crashing the page. */
function formatJson(value: unknown): string {
  if (value === null || value === undefined) return "null";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "Не удалось отобразить значение как JSON.";
  }
}

/**
 * Collapsible, read-only JSON viewer. Renders as plain text content (React
 * escapes it by default) — never `dangerouslySetInnerHTML` — so it is safe
 * even for adversarial or malformed stored JSON.
 */
export function JsonBlock({ title, value, defaultOpen = false }: JsonBlockProps) {
  return (
    <details className="json-block-details" open={defaultOpen}>
      <summary>{title}</summary>
      <pre className="json-block">{formatJson(value)}</pre>
    </details>
  );
}

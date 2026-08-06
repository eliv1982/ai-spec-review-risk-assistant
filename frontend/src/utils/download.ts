/**
 * Small download utilities shared by every CSV export flow: extracting and
 * sanitizing a filename that came from a `Content-Disposition` response
 * header (never trusted as-is — it travels over the wire, and defense in
 * depth matters even though this app's own backend only ever emits safe
 * ASCII literals), and triggering the actual browser download from a `Blob`.
 */

const DEFAULT_FALLBACK_FILENAME = "export.csv";

/**
 * Extracts the `filename` parameter from a `Content-Disposition` header
 * value (`attachment; filename="foo.csv"`, with or without quotes). Returns
 * `null` for a missing or unparseable header — callers must always have a
 * safe fallback ready, never assume this succeeds.
 */
export function extractContentDispositionFilename(headerValue: string | null): string | null {
  if (!headerValue) return null;
  const match = /filename\s*=\s*"?([^";]+)"?/i.exec(headerValue);
  return match ? match[1].trim() : null;
}

function isControlCodePoint(codePoint: number): boolean {
  return codePoint <= 0x1f || codePoint === 0x7f;
}

/**
 * Sanitizes an untrusted candidate filename: strips path separators and
 * control characters, then falls back to `fallback` if nothing usable
 * remains — an empty string, or a value made up entirely of dots (which
 * would otherwise resolve to a path-traversal segment or a hidden/parent
 * directory reference on save). Never throws.
 */
export function sanitizeFilename(candidate: string, fallback: string = DEFAULT_FALLBACK_FILENAME): string {
  const withoutSeparators = candidate.replace(/[\\/]/g, "");
  const withoutControlChars = Array.from(withoutSeparators)
    .filter((ch) => !isControlCodePoint(ch.codePointAt(0) ?? 0))
    .join("");
  const trimmed = withoutControlChars.trim();
  if (trimmed === "" || /^\.+$/.test(trimmed)) return fallback;
  return trimmed;
}

/**
 * Triggers a browser download of `blob` as `filename` via a temporary object
 * URL and anchor element. `URL.revokeObjectURL(url)` always runs exactly
 * once after a successful `createObjectURL` — via an outer try/finally that
 * wraps every DOM step (`createElement`, `appendChild`, `click`,
 * `removeChild`) — so a browser quirk in any one of them can never leak the
 * object URL. Anchor removal is a separate, inner try/finally so a failure
 * there (e.g. the anchor was already detached) can never prevent the revoke.
 * Errors from any step still propagate to the caller; only the revoke is
 * guaranteed.
 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    try {
      anchor.click();
    } finally {
      document.body.removeChild(anchor);
    }
  } finally {
    URL.revokeObjectURL(url);
  }
}

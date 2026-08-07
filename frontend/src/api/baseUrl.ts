/** Falls back to the local backend's default `uvicorn app.main:app` address
 * in development and to the reverse proxy's same-origin path in production. */
const DEFAULT_API_BASE_URL = import.meta.env.DEV ? "http://127.0.0.1:8000/api" : "/api";

const API_SEGMENT = "api";

/**
 * Thrown by `normalizeApiBaseUrl` for a `VITE_API_BASE_URL` value that isn't
 * a supported backend base URL. A same-origin `/api` path is accepted for the
 * production reverse-proxy deployment. Carries the raw offending value for logging;
 * `client.ts` catches this and shows a safe Russian configuration message
 * instead of a raw stack trace.
 */
export class ApiBaseUrlConfigError extends Error {
  readonly rawValue: string;

  constructor(message: string, rawValue: string) {
    super(message);
    this.name = "ApiBaseUrlConfigError";
    this.rawValue = rawValue;
  }
}

/**
 * A supported pathname is either empty (origin-only) or made up of one or
 * more repeated `/api` segments (`/api`, `/api/api`, ...), with any number
 * of trailing slashes. Returns `true` if `pathname` matches that shape.
 * Never does a blind string replace of "api" — only inspects path segments,
 * so a hostname or unrelated path segment that happens to contain "api" as
 * a substring (e.g. `/apiv2`) is correctly rejected, and a hostname like
 * `api-host.example` is never touched at all (this function never sees it).
 */
function isSupportedApiPathname(pathname: string): boolean {
  const withoutTrailingSlashes = pathname.replace(/\/+$/, "");
  if (withoutTrailingSlashes === "") return true;
  const segments = withoutTrailingSlashes.split("/").filter((segment) => segment !== "");
  return segments.length > 0 && segments.every((segment) => segment === API_SEGMENT);
}

/**
 * Normalizes a configured backend base URL so callers can safely append a
 * leading-slash path (e.g. `/documents`) to the result without producing
 * `/api/api`, a missing `/api`, or doubled trailing slashes.
 *
 * Accepts the same-origin `/api` path used by the production container, or an
 * absolute `http(s)` URL that is either origin-only
 * (`http://host:8000`) or ends in one-or-more repeated `/api` segments
 * (`http://host:8000/api`, `.../api/api`, ...), with or without trailing
 * slashes. Rejects (throws `ApiBaseUrlConfigError`) anything else: arbitrary
 * relative URLs, non-`http(s)` schemes, a query string or fragment, or a pathname
 * that isn't purely `/api` repeats — these are treated as misconfiguration,
 * not silently coerced into a possibly-wrong endpoint.
 */
export function normalizeApiBaseUrl(rawValue: string | undefined | null): string {
  const trimmed = (rawValue ?? "").trim();
  const source = trimmed || DEFAULT_API_BASE_URL;

  // The production container serves the SPA and proxies the API on one origin.
  // Keep this narrowly scoped to the same supported `/api` path shape; arbitrary
  // relative paths remain configuration errors.
  if (/^\/api(?:\/api)*\/*$/.test(source)) {
    return "/api";
  }

  let parsed: URL;
  try {
    parsed = new URL(source);
  } catch {
    throw new ApiBaseUrlConfigError(
      `VITE_API_BASE_URL must be an absolute URL, got ${JSON.stringify(source)}`,
      source,
    );
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new ApiBaseUrlConfigError(
      `VITE_API_BASE_URL must use http or https, got ${JSON.stringify(source)}`,
      source,
    );
  }

  if (parsed.search) {
    throw new ApiBaseUrlConfigError(
      `VITE_API_BASE_URL must not include a query string, got ${JSON.stringify(source)}`,
      source,
    );
  }

  if (parsed.hash) {
    throw new ApiBaseUrlConfigError(
      `VITE_API_BASE_URL must not include a fragment, got ${JSON.stringify(source)}`,
      source,
    );
  }

  if (!isSupportedApiPathname(parsed.pathname)) {
    throw new ApiBaseUrlConfigError(
      `VITE_API_BASE_URL path must be empty or consist of one or more "/api" segments, ` +
        `got ${JSON.stringify(source)}`,
      source,
    );
  }

  // `origin` is derived structurally by the URL parser (protocol + host),
  // never by string substitution, so a host containing "api" is untouched.
  return `${parsed.origin}/api`;
}

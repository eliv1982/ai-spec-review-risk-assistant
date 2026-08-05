import { ApiBaseUrlConfigError, normalizeApiBaseUrl } from "./baseUrl";
import type { ApiErrorBody } from "../types/api";

export function getApiBaseUrl(): string {
  return normalizeApiBaseUrl(import.meta.env.VITE_API_BASE_URL);
}

export type ApiErrorKind = "network" | "http" | "validation" | "invalid_response" | "config";

/**
 * Thrown by every `request()` call. `message` is always a safe, user-facing
 * Russian string; the raw technical details (HTTP status, backend `detail`,
 * or the underlying network/parsing exception) are preserved on
 * `status`/`detail` for logging, never rendered directly to the user.
 */
export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status?: number;
  readonly detail?: unknown;

  constructor(params: { kind: ApiErrorKind; message: string; status?: number; detail?: unknown }) {
    super(params.message);
    this.name = "ApiError";
    this.kind = params.kind;
    this.status = params.status;
    this.detail = params.detail;
  }
}

/** True for a `fetch`/`AbortController` cancellation. Checks `name` directly
 * rather than `instanceof Error`/`instanceof DOMException`, since `DOMException`
 * does not consistently subclass `Error` across environments (Node, jsdom,
 * browsers), while every implementation sets `name: "AbortError"`. */
export function isAbortError(err: unknown): boolean {
  return typeof err === "object" && err !== null && (err as { name?: unknown }).name === "AbortError";
}

const INVALID_RESPONSE_MESSAGE =
  "Сервер вернул некорректный ответ. Повторите попытку или обратитесь к администратору.";

const GENERIC_VALIDATION_MESSAGE = "Сервер отклонил данные запроса. Проверьте введённые значения.";

const BODY_READ_FAILURE_MESSAGE =
  "Не удалось получить ответ сервера. Проверьте подключение и повторите попытку.";

const CONFIG_ERROR_MESSAGE = "Некорректно настроен адрес API.";

/** Russian labels for the path fields a FastAPI/Pydantic `uuid_parsing` (or
 * `uuid_type`) validation error can point at in this app's routes. */
const UUID_FIELD_LABELS: Record<string, string> = {
  review_id: "проверки",
  document_id: "документа",
};

/** The subset of a FastAPI/Pydantic validation-error item this app actually
 * reads, confirmed present with the right runtime types. Nothing about a
 * validation `detail` array element is trusted until it passes this check —
 * a malformed proxy/error body (missing `loc`, `loc` not an array, the item
 * itself being `null` or a string, etc.) safely falls through to the
 * generic message instead of throwing while reading `.loc.length`. */
interface KnownValidationItem {
  loc: Array<string | number>;
  type: string;
}

function parseValidationItem(item: unknown): KnownValidationItem | null {
  if (typeof item !== "object" || item === null) return null;
  const record = item as Record<string, unknown>;
  const { loc, type } = record;
  if (!Array.isArray(loc) || !loc.every((seg) => typeof seg === "string" || typeof seg === "number")) {
    return null;
  }
  if (typeof type !== "string") return null;
  return { loc, type };
}

function messageForValidationDetail(detail: unknown[]): string {
  const first = parseValidationItem(detail[0]);
  if (!first) return GENERIC_VALIDATION_MESSAGE;

  if (first.type === "uuid_parsing" || first.type === "uuid_type") {
    const field = first.loc[first.loc.length - 1];
    const label = typeof field === "string" ? UUID_FIELD_LABELS[field] : undefined;
    return label ? `Некорректный идентификатор ${label}.` : "Некорректный идентификатор.";
  }

  // Never surface the raw (English) Pydantic `msg` for unrecognized types.
  return GENERIC_VALIDATION_MESSAGE;
}

function fallbackMessageForStatus(status: number): string {
  if (status === 404) return "Запрошенные данные не найдены.";
  if (status === 422) return GENERIC_VALIDATION_MESSAGE;
  if (status >= 500) return "Внутренняя ошибка сервера. Попробуйте повторить запрос позже.";
  return "Произошла ошибка при обращении к серверу.";
}

/**
 * Reads a `Response` body as text, translating a stream/network failure
 * (the fetch itself succeeded, but the body could not be read) into a safe
 * `ApiError` instead of letting a raw `TypeError` escape. An abort is
 * rethrown unchanged so callers keep treating it as a cancellation, never a
 * user-facing error.
 */
async function readResponseText(response: Response): Promise<string> {
  try {
    return await response.text();
  } catch (cause) {
    if (isAbortError(cause)) throw cause;
    throw new ApiError({
      kind: "network",
      message: BODY_READ_FAILURE_MESSAGE,
      detail: cause,
    });
  }
}

/** Lenient parse used only for non-2xx error bodies: malformed/non-JSON
 * content still resolves to a safe fallback message (via `undefined`)
 * rather than throwing; only a body-read failure (network/stream error) or
 * an abort propagates. */
async function parseJsonLeniently(response: Response): Promise<unknown> {
  const text = await readResponseText(response);
  if (!text) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

async function buildHttpError(response: Response): Promise<ApiError> {
  const body = (await parseJsonLeniently(response)) as ApiErrorBody | undefined;
  const detail = body?.detail;

  if (response.status === 422 && Array.isArray(detail)) {
    return new ApiError({
      kind: "validation",
      message: messageForValidationDetail(detail),
      status: response.status,
      detail,
    });
  }

  if (typeof detail === "string" && detail.trim()) {
    return new ApiError({
      kind: "http",
      message: detail,
      status: response.status,
      detail,
    });
  }

  return new ApiError({
    kind: "http",
    message: fallbackMessageForStatus(response.status),
    status: response.status,
    detail: body,
  });
}

function invalidResponseError(status: number, cause: unknown): ApiError {
  return new ApiError({
    kind: "invalid_response",
    message: INVALID_RESPONSE_MESSAGE,
    status,
    detail: cause,
  });
}

/**
 * Generic request helper. The response body is parsed strictly as `unknown`
 * first — never blindly cast with `as T` — and then handed to the
 * endpoint-specific `validate` function, which throws on any contract
 * violation (including an unrecognized closed-enum value). Both an
 * empty/non-JSON body and a validator rejection collapse into the same safe
 * `invalid_response` `ApiError`, never a raw parser exception or stack
 * trace surfaced to the UI.
 */
export async function request<T>(
  path: string,
  init: RequestInit | undefined,
  validate: (data: unknown) => T,
): Promise<T> {
  let baseUrl: string;
  try {
    baseUrl = getApiBaseUrl();
  } catch (cause) {
    if (cause instanceof ApiBaseUrlConfigError) {
      throw new ApiError({ kind: "config", message: CONFIG_ERROR_MESSAGE, detail: cause });
    }
    throw cause;
  }
  const url = `${baseUrl}${path}`;
  let response: Response;

  try {
    response = await fetch(url, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
  } catch (cause) {
    if (isAbortError(cause)) throw cause;
    throw new ApiError({
      kind: "network",
      message: "Не удалось соединиться с сервером. Проверьте подключение и адрес backend.",
      detail: cause,
    });
  }

  if (!response.ok) {
    throw await buildHttpError(response);
  }

  const raw = await readResponseText(response);
  if (raw.trim() === "") {
    throw invalidResponseError(response.status, "empty response body");
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch (cause) {
    throw invalidResponseError(response.status, cause);
  }

  try {
    return validate(parsed);
  } catch (cause) {
    throw invalidResponseError(response.status, cause);
  }
}

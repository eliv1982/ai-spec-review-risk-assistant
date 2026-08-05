import json
from typing import Any, List, Optional

import pydantic
from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    OpenAIError,
)

from app.config import Settings, get_settings
from app.schemas.review import ModelReviewDraft

from .errors import (
    LLMAPIError,
    LLMClientError,
    LLMConfigurationError,
    LLMInvalidJSONError,
    LLMProviderError,
    LLMSchemaMismatchError,
    LLMTransportError,
)
from .prompts import SYSTEM_PROMPT

_JSON_DECODE_ERROR_TYPES = frozenset({"json_invalid"})


class OpenAIReviewClient:
    """Sends specification text to OpenAI Structured Outputs and returns a
    validated ModelReviewDraft (REVIEW_SCHEMA.md, "A. ModelReviewDraft").

    Uses the synchronous, non-streaming Responses API with `ModelReviewDraft`
    as the strict `text_format`, via `responses.with_raw_response.parse(...)`
    rather than `responses.parse(...)` directly: the raw response lets the
    top-level provider `status` be checked *before* the SDK's Structured
    Outputs post-parser runs, so a non-completed response (for example
    `status="incomplete"`, which carries a partial/truncated `output_text`)
    is never misclassified as an invalid-JSON or schema-mismatch failure of
    that partial text. `raw_response.parse()` — which triggers the SDK's
    Structured Outputs parsing — is only called once `status == "completed"`.

    Does not touch the database, does not run deterministic QC, and does not
    build a `FinalReview` — those remain the review service's and QC
    service's responsibility.

    `review()` is itself wrapped in an outer safety boundary that spans the
    whole operation — configuration validation, lazily constructing the real
    `OpenAI` client, the initial `with_raw_response.parse(...)` call, the
    status gate, completed-response parsing, and draft extraction — so any
    ordinary exception raised anywhere in that chain (a typed OpenAI SDK
    exception the inner handling missed, or a plain `TypeError`/
    `AttributeError`/`RuntimeError`) is guaranteed to come out as a
    `LLMClientError` subclass rather than escaping raw.
    """

    def __init__(self, *, settings: Optional[Settings] = None, client: Optional[OpenAI] = None) -> None:
        self._settings = settings if settings is not None else get_settings()
        self._injected_client = client

    def review(self, document_text: str) -> ModelReviewDraft:
        try:
            return self._review_impl(document_text)
        except LLMClientError:
            raise
        except (APITimeoutError, APIConnectionError) as exc:
            raise LLMTransportError("Не удалось установить соединение с провайдером LLM.") from exc
        except APIStatusError as exc:
            raise LLMAPIError(
                _api_error_message(exc.status_code),
                status_code=exc.status_code,
                request_id=exc.request_id,
            ) from exc
        except APIResponseValidationError as exc:
            raise LLMProviderError("Провайдер вернул ответ с некорректной структурой.") from exc
        except OpenAIError as exc:
            raise LLMProviderError("Не удалось выполнить запрос к провайдеру LLM.") from exc
        except Exception as exc:
            raise LLMProviderError(
                "Не удалось выполнить проверку документа с помощью провайдера LLM."
            ) from exc

    def _review_impl(self, document_text: str) -> ModelReviewDraft:
        api_key = self._settings.openai_api_key.strip()
        model = self._settings.openai_model.strip()

        if not api_key:
            raise LLMConfigurationError(
                "OPENAI_API_KEY не настроен: переменная окружения отсутствует или пуста."
            )
        if not model:
            raise LLMConfigurationError(
                "OPENAI_MODEL не настроен: переменная окружения отсутствует или пуста."
            )

        client = self._injected_client if self._injected_client is not None else OpenAI(api_key=api_key)

        try:
            raw_response = client.responses.with_raw_response.parse(
                model=model,
                instructions=SYSTEM_PROMPT,
                input=document_text,
                text_format=ModelReviewDraft,
                store=False,
            )
        except APITimeoutError as exc:
            raise LLMTransportError("Истекло время ожидания ответа провайдера LLM.") from exc
        except APIConnectionError as exc:
            raise LLMTransportError("Не удалось установить соединение с провайдером LLM.") from exc
        except APIStatusError as exc:
            raise LLMAPIError(
                _api_error_message(exc.status_code),
                status_code=exc.status_code,
                request_id=exc.request_id,
            ) from exc
        except OpenAIError as exc:
            raise LLMProviderError("Провайдер LLM не смог обработать запрос.") from exc

        # Gate on the top-level provider status read straight from the raw
        # body, before letting the SDK run its Structured Outputs
        # post-parser. Otherwise a non-completed response (e.g. "incomplete")
        # with a partial/truncated output_text gets fed into JSON/schema
        # validation and is misclassified as LLMInvalidJSONError or
        # LLMSchemaMismatchError instead of the provider failure it is.
        _ensure_response_completed(raw_response)

        response = _parse_completed_response(raw_response)

        return _extract_draft(response)


def _api_error_message(status_code: Optional[int]) -> str:
    if status_code is None:
        return "Провайдер LLM вернул ошибку HTTP."
    return f"Провайдер LLM вернул ошибку HTTP {status_code}."


def _ensure_response_completed(raw_response: Any) -> None:
    """Raise LLMProviderError for any non-"completed" top-level provider
    status (incomplete, failed, queued, in_progress, ...), read directly
    from the raw response body via the public `with_raw_response` surface.

    This runs before `raw_response.parse()`, so the SDK's Structured Outputs
    post-parser never runs against a partial/truncated `output_text`. The
    raw body is read only to extract this one field: it is never included in
    an exception message or attribute.
    """
    try:
        payload = json.loads(raw_response.text)
        status = payload.get("status") if isinstance(payload, dict) else None
    except (TypeError, ValueError) as exc:
        raise LLMProviderError("Провайдер LLM вернул ответ в неожиданном формате.") from exc

    if status != "completed":
        raise LLMProviderError("Провайдер не завершил формирование структурированного ответа.")


def _parse_completed_response(raw_response: Any) -> Any:
    """Turn a "completed" raw response into the SDK's parsed `Response`
    object, translating every exception `raw_response.parse()` can raise
    into a typed `LLMClientError` subclass so none of it — a SDK/provider
    exception, or a raw `TypeError`/`AttributeError` from parsing a
    structurally malformed envelope — ever crosses `review()`'s typed
    boundary. Only a fixed safe message and, for `LLMAPIError`, the status
    code / request id are attached to the resulting error; the original
    exception is preserved solely as `__cause__`, never copied into a public
    attribute or message (no body, request, response, or raw payload).
    """
    try:
        return raw_response.parse()
    except pydantic.ValidationError as exc:
        raise _classify_validation_error(exc) from exc
    except LLMClientError:
        raise
    except (APITimeoutError, APIConnectionError) as exc:
        raise LLMTransportError("Не удалось получить ответ провайдера LLM.") from exc
    except APIStatusError as exc:
        raise LLMAPIError(
            _api_error_message(exc.status_code),
            status_code=exc.status_code,
            request_id=exc.request_id,
        ) from exc
    except APIResponseValidationError as exc:
        raise LLMProviderError("Провайдер вернул ответ с некорректной структурой.") from exc
    except OpenAIError as exc:
        raise LLMProviderError("Не удалось обработать ответ провайдера LLM.") from exc
    except Exception as exc:
        raise LLMProviderError("Не удалось обработать структурированный ответ провайдера LLM.") from exc


def _classify_validation_error(exc: pydantic.ValidationError) -> LLMClientError:
    """Classify a validation failure raised while the SDK parsed the model's
    response text as `ModelReviewDraft` (`pydantic.ValidationError.errors()`).

    A JSON decode failure produces exclusively `json_invalid` entries, since
    parsing never reaches field validation; any other error type means the
    text was valid JSON that failed schema validation.
    """
    errors: List[dict] = exc.errors()
    if errors and all(error.get("type") in _JSON_DECODE_ERROR_TYPES for error in errors):
        return LLMInvalidJSONError("Ответ модели не является корректным JSON.")
    return LLMSchemaMismatchError("Ответ модели не соответствует схеме ModelReviewDraft.")


def _extract_draft(response: Any) -> ModelReviewDraft:
    for output in getattr(response, "output", None) or []:
        if getattr(output, "type", None) != "message":
            continue
        for content in getattr(output, "content", None) or []:
            if getattr(content, "type", None) == "refusal":
                raise LLMProviderError("Провайдер LLM отказался сформировать структурированный ответ.")

    if getattr(response, "status", None) == "incomplete":
        raise LLMProviderError("Провайдер LLM вернул неполный ответ.")

    draft = getattr(response, "output_parsed", None)
    if draft is None:
        raise LLMProviderError("Провайдер LLM не вернул структурированный результат.")

    return draft

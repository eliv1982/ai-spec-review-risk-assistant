import json

import httpx
import pytest
from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    OpenAIError,
)

from app.config import Settings
from app.llm.client import OpenAIReviewClient
from app.llm.errors import (
    LLMAPIError,
    LLMClientError,
    LLMConfigurationError,
    LLMInvalidJSONError,
    LLMProviderError,
    LLMSchemaMismatchError,
    LLMTransportError,
)
from app.llm.prompts import SYSTEM_PROMPT
from app.schemas.review import ModelReviewDraft

DOCUMENT_TEXT = (
    "Система должна позволять пользователю подписываться на уведомления и "
    "настраивать канал доставки. " * 5
)

VALID_DRAFT_KWARGS = dict(
    summary="Итоговое резюме проверки спецификации.",
    risks=[],
    missing_requirements=[],
    contradictions=[],
    questions_to_client=["Каков период хранения истории уведомлений?"],
    acceptance_criteria=["Given a subscribed user, when an event occurs, then a notification is sent."],
    confidence="medium",
    document_readiness="needs_clarification",
    model_needs_review=False,
)


def _settings(*, api_key: str = "sk-test-secret-value", model: str = "gpt-test-model") -> Settings:
    return Settings(
        openai_api_key=api_key,
        openai_model=model,
        database_url="sqlite:///:memory:",
        backend_cors_origins="http://localhost:5173",
    )


# ---------------------------------------------------------------------------
# Fakes for the injected client. The provider call now goes through
# `client.responses.with_raw_response.parse(...)`, which returns a raw
# response object exposing `.text` (the undecoded top-level JSON envelope,
# readable before Structured Outputs post-processing) and `.parse()` (which
# triggers that post-processing). Fakes mirror only that minimal surface.
# ---------------------------------------------------------------------------


class _FakeContent:
    def __init__(self, type_: str) -> None:
        self.type = type_


class _FakeMessageOutput:
    def __init__(self, content_types):
        self.type = "message"
        self.content = [_FakeContent(t) for t in content_types]


class _FakeResponse:
    """Stands in for the `ParsedResponse` returned by `raw_response.parse()`."""

    def __init__(self, *, output_parsed=None, status: str = "completed", output=None) -> None:
        self.output_parsed = output_parsed
        self.status = status
        self.output = output if output is not None else []


class _FakeRawResponse:
    """Stands in for the `LegacyAPIResponse` returned by `with_raw_response.parse(...)`."""

    def __init__(self, *, status: str, parsed_result=None, parse_exception=None) -> None:
        self.text = json.dumps({"status": status})
        self._parsed_result = parsed_result
        self._parse_exception = parse_exception
        self.parse_call_count = 0

    def parse(self):
        self.parse_call_count += 1
        if self._parse_exception is not None:
            raise self._parse_exception
        return self._parsed_result


def _completed_raw_response(parsed_result) -> _FakeRawResponse:
    return _FakeRawResponse(status="completed", parsed_result=parsed_result)


def _completed_raw_response_raising(exception) -> _FakeRawResponse:
    return _FakeRawResponse(status="completed", parse_exception=exception)


class _FakeWithRawResponse:
    def __init__(self, *, raw_response=None, exception=None, capture: dict | None = None) -> None:
        self._raw_response = raw_response
        self._exception = exception
        self._capture = capture
        self.called = False

    def parse(self, **kwargs):
        self.called = True
        if self._capture is not None:
            self._capture.update(kwargs)
        if self._exception is not None:
            raise self._exception
        return self._raw_response


class _FakeResponses:
    def __init__(self, *, raw_response=None, exception=None, capture: dict | None = None) -> None:
        self.with_raw_response = _FakeWithRawResponse(raw_response=raw_response, exception=exception, capture=capture)


class _FakeOpenAIClient:
    def __init__(self, *, raw_response=None, exception=None, capture: dict | None = None) -> None:
        self.responses = _FakeResponses(raw_response=raw_response, exception=exception, capture=capture)


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.openai.com/v1/responses")


def _status_error(status_code: int, *, request_id: str | None = None, raw_message: str = "boom-raw-body") -> APIStatusError:
    headers = {"x-request-id": request_id} if request_id else {}
    response = httpx.Response(
        status_code,
        request=_request(),
        headers=headers,
        json={"error": {"message": raw_message, "type": "server_error"}},
    )
    return APIStatusError(raw_message, response=response, body={"error": {"message": raw_message}})


def _validation_error_from_text(text: str):
    try:
        ModelReviewDraft.model_validate_json(text)
    except Exception as exc:  # the SDK raises exactly this kind of exception during parsing
        return exc
    raise AssertionError("expected model_validate_json to raise")


# ---------------------------------------------------------------------------
# Provider call arguments
# ---------------------------------------------------------------------------


def test_provider_call_uses_configured_model_instructions_input_and_flags():
    capture: dict = {}
    draft = ModelReviewDraft(**VALID_DRAFT_KWARGS)
    fake_client = _FakeOpenAIClient(
        raw_response=_completed_raw_response(_FakeResponse(output_parsed=draft)),
        capture=capture,
    )
    client = OpenAIReviewClient(settings=_settings(model="gpt-configured-model"), client=fake_client)

    client.review(DOCUMENT_TEXT)

    assert capture["model"] == "gpt-configured-model"
    assert capture["instructions"] == SYSTEM_PROMPT
    assert capture["input"] == DOCUMENT_TEXT
    assert capture["text_format"] is ModelReviewDraft
    assert capture["store"] is False


# ---------------------------------------------------------------------------
# Successful parse
# ---------------------------------------------------------------------------


def test_successful_parse_returns_model_review_draft_instance():
    draft = ModelReviewDraft(**VALID_DRAFT_KWARGS)
    fake_client = _FakeOpenAIClient(raw_response=_completed_raw_response(_FakeResponse(output_parsed=draft)))
    client = OpenAIReviewClient(settings=_settings(), client=fake_client)

    result = client.review(DOCUMENT_TEXT)

    assert result is draft
    assert isinstance(result, ModelReviewDraft)


def test_completed_response_calls_raw_response_parse_exactly_once():
    draft = ModelReviewDraft(**VALID_DRAFT_KWARGS)
    raw = _completed_raw_response(_FakeResponse(output_parsed=draft))
    fake_client = _FakeOpenAIClient(raw_response=raw)
    client = OpenAIReviewClient(settings=_settings(), client=fake_client)

    client.review(DOCUMENT_TEXT)

    assert raw.parse_call_count == 1


# ---------------------------------------------------------------------------
# Configuration errors (provider must never be called)
# ---------------------------------------------------------------------------


def test_empty_api_key_raises_configuration_error_without_calling_provider():
    fake_client = _FakeOpenAIClient()
    client = OpenAIReviewClient(settings=_settings(api_key=""), client=fake_client)

    with pytest.raises(LLMConfigurationError):
        client.review(DOCUMENT_TEXT)

    assert fake_client.responses.with_raw_response.called is False


def test_blank_api_key_after_trim_raises_configuration_error_without_calling_provider():
    fake_client = _FakeOpenAIClient()
    client = OpenAIReviewClient(settings=_settings(api_key="   "), client=fake_client)

    with pytest.raises(LLMConfigurationError):
        client.review(DOCUMENT_TEXT)

    assert fake_client.responses.with_raw_response.called is False


def test_empty_model_raises_configuration_error_without_calling_provider():
    fake_client = _FakeOpenAIClient()
    client = OpenAIReviewClient(settings=_settings(model=""), client=fake_client)

    with pytest.raises(LLMConfigurationError):
        client.review(DOCUMENT_TEXT)

    assert fake_client.responses.with_raw_response.called is False


def test_blank_model_after_trim_raises_configuration_error_without_calling_provider():
    fake_client = _FakeOpenAIClient()
    client = OpenAIReviewClient(settings=_settings(model="\t\n"), client=fake_client)

    with pytest.raises(LLMConfigurationError):
        client.review(DOCUMENT_TEXT)

    assert fake_client.responses.with_raw_response.called is False


def test_configuration_error_message_is_russian_and_does_not_leak_api_key():
    fake_client = _FakeOpenAIClient()
    client = OpenAIReviewClient(settings=_settings(api_key="", model="gpt-test-model"), client=fake_client)

    with pytest.raises(LLMConfigurationError) as excinfo:
        client.review(DOCUMENT_TEXT)

    message = str(excinfo.value)
    assert "OPENAI_API_KEY" in message
    assert "sk-test-secret-value" not in message


# ---------------------------------------------------------------------------
# Transport errors
# ---------------------------------------------------------------------------


def test_timeout_raises_transport_error():
    fake_client = _FakeOpenAIClient(exception=APITimeoutError(request=_request()))
    client = OpenAIReviewClient(settings=_settings(), client=fake_client)

    with pytest.raises(LLMTransportError):
        client.review(DOCUMENT_TEXT)


def test_connection_failure_raises_transport_error():
    fake_client = _FakeOpenAIClient(exception=APIConnectionError(request=_request()))
    client = OpenAIReviewClient(settings=_settings(), client=fake_client)

    with pytest.raises(LLMTransportError):
        client.review(DOCUMENT_TEXT)


def test_transport_error_preserves_exception_chain():
    original = APITimeoutError(request=_request())
    fake_client = _FakeOpenAIClient(exception=original)
    client = OpenAIReviewClient(settings=_settings(), client=fake_client)

    with pytest.raises(LLMTransportError) as excinfo:
        client.review(DOCUMENT_TEXT)

    assert excinfo.value.__cause__ is original


# ---------------------------------------------------------------------------
# HTTP / API errors
# ---------------------------------------------------------------------------


def test_http_status_error_raises_api_error_with_safe_status_code_and_request_id():
    fake_client = _FakeOpenAIClient(exception=_status_error(429, request_id="req-abc-123"))
    client = OpenAIReviewClient(settings=_settings(), client=fake_client)

    with pytest.raises(LLMAPIError) as excinfo:
        client.review(DOCUMENT_TEXT)

    error = excinfo.value
    assert error.status_code == 429
    assert error.request_id == "req-abc-123"


def test_api_error_message_does_not_leak_raw_response_body():
    fake_client = _FakeOpenAIClient(exception=_status_error(500, raw_message="internal secret trace details"))
    client = OpenAIReviewClient(settings=_settings(), client=fake_client)

    with pytest.raises(LLMAPIError) as excinfo:
        client.review(DOCUMENT_TEXT)

    message = str(excinfo.value)
    assert "internal secret trace details" not in message
    assert "500" in message


# ---------------------------------------------------------------------------
# Provider-level failures: refusal, missing output_parsed, generic SDK error
# ---------------------------------------------------------------------------


def test_refusal_raises_provider_error():
    response = _FakeResponse(
        output_parsed=None,
        status="completed",
        output=[_FakeMessageOutput(["refusal"])],
    )
    fake_client = _FakeOpenAIClient(raw_response=_completed_raw_response(response))
    client = OpenAIReviewClient(settings=_settings(), client=fake_client)

    with pytest.raises(LLMProviderError):
        client.review(DOCUMENT_TEXT)


def test_missing_output_parsed_raises_provider_error():
    response = _FakeResponse(output_parsed=None, status="completed", output=[])
    fake_client = _FakeOpenAIClient(raw_response=_completed_raw_response(response))
    client = OpenAIReviewClient(settings=_settings(), client=fake_client)

    with pytest.raises(LLMProviderError):
        client.review(DOCUMENT_TEXT)


def test_generic_openai_sdk_failure_raises_provider_error():
    fake_client = _FakeOpenAIClient(exception=OpenAIError("some unexpected SDK failure"))
    client = OpenAIReviewClient(settings=_settings(), client=fake_client)

    with pytest.raises(LLMProviderError):
        client.review(DOCUMENT_TEXT)


# ---------------------------------------------------------------------------
# Outer safety boundary: an ordinary (non-OpenAIError) exception raised by
# the *initial* `client.responses.with_raw_response.parse(...)` call — before
# any raw response exists — must still come out of review() as a typed
# LLMClientError, never escape raw. This is what the outer try/except
# wrapped around the whole of review() guarantees, on top of the
# OpenAIError-specific handling already inside _review_impl.
# ---------------------------------------------------------------------------


_INITIAL_CALL_DANGEROUS_TEXT = (
    "sk-test-secret-value Authorization: Bearer super-secret-token "
    + DOCUMENT_TEXT
    + " raw-provider-body-marker"
)


@pytest.mark.parametrize("exception_cls", [TypeError, AttributeError, RuntimeError])
def test_initial_call_ordinary_exception_raises_provider_error_without_leaking(exception_cls):
    original = exception_cls(_INITIAL_CALL_DANGEROUS_TEXT)
    fake_client = _FakeOpenAIClient(exception=original)
    client = OpenAIReviewClient(settings=_settings(), client=fake_client)

    with pytest.raises(LLMProviderError) as excinfo:
        client.review(DOCUMENT_TEXT)

    error = excinfo.value
    assert error.__cause__ is original

    surfaces = " ".join([str(error), repr(error), str(error.args), str(vars(error))])
    assert "sk-test-secret-value" not in surfaces
    assert "Authorization: Bearer" not in surfaces
    assert DOCUMENT_TEXT not in surfaces
    assert "raw-provider-body-marker" not in surfaces

    for attr in ("body", "request", "response", "document_text", "raw_response"):
        assert not hasattr(error, attr)


def test_review_does_not_catch_base_exception():
    # KeyboardInterrupt is a BaseException, not an Exception: the outer
    # boundary's `except Exception` must not swallow it.
    fake_client = _FakeOpenAIClient(exception=KeyboardInterrupt())
    client = OpenAIReviewClient(settings=_settings(), client=fake_client)

    with pytest.raises(KeyboardInterrupt):
        client.review(DOCUMENT_TEXT)


# ---------------------------------------------------------------------------
# Client construction: lazily constructing the real OpenAI client is inside
# the outer safety boundary too. No real SDK client or network is involved —
# `OpenAI` is monkeypatched inside the client module.
# ---------------------------------------------------------------------------


def test_client_construction_failure_raises_provider_error(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("sk-test-secret-value failed to construct httpx transport")

    monkeypatch.setattr("app.llm.client.OpenAI", _boom)

    client = OpenAIReviewClient(settings=_settings())  # no injected client: takes the OpenAI(...) branch

    with pytest.raises(LLMProviderError) as excinfo:
        client.review(DOCUMENT_TEXT)

    message = str(excinfo.value)
    assert "sk-test-secret-value" not in message
    assert "failed to construct httpx transport" not in message


# ---------------------------------------------------------------------------
# Pass-through: an already-classified LLMClientError raised from the initial
# call path must surface unchanged, not be re-wrapped by the outer boundary.
# ---------------------------------------------------------------------------


def test_initial_call_own_llm_client_error_is_not_rewrapped():
    original = LLMAPIError(
        "ошибка провайдера уже классифицирована",
        status_code=418,
        request_id="req-preexisting",
    )
    fake_client = _FakeOpenAIClient(exception=original)
    client = OpenAIReviewClient(settings=_settings(), client=fake_client)

    with pytest.raises(LLMAPIError) as excinfo:
        client.review(DOCUMENT_TEXT)

    assert excinfo.value is original
    assert excinfo.value.status_code == 418
    assert excinfo.value.request_id == "req-preexisting"


# ---------------------------------------------------------------------------
# Codex finding: a non-completed top-level status must always raise
# LLMProviderError, and must never reach Structured Outputs post-parsing at
# all — regardless of what the (irrelevant, partial) output_text looks like.
# ---------------------------------------------------------------------------


def test_incomplete_response_raises_provider_error():
    raw = _FakeRawResponse(status="incomplete")
    fake_client = _FakeOpenAIClient(raw_response=raw)
    client = OpenAIReviewClient(settings=_settings(), client=fake_client)

    with pytest.raises(LLMProviderError):
        client.review(DOCUMENT_TEXT)

    assert raw.parse_call_count == 0


def test_incomplete_response_with_malformed_partial_json_raises_provider_error():
    # If `.parse()` were called despite the incomplete status, this exception
    # would surface and get misclassified as LLMInvalidJSONError — the exact
    # Codex finding. It must never be triggered.
    would_be_json_error = _validation_error_from_text("this is not valid json at all {{{")
    raw = _FakeRawResponse(status="incomplete", parse_exception=would_be_json_error)
    fake_client = _FakeOpenAIClient(raw_response=raw)
    client = OpenAIReviewClient(settings=_settings(), client=fake_client)

    with pytest.raises(LLMProviderError):
        client.review(DOCUMENT_TEXT)

    assert raw.parse_call_count == 0


def test_incomplete_response_with_schema_invalid_partial_json_raises_provider_error():
    # Same as above, but the exception `.parse()` would raise is one that
    # would have been classified as LLMSchemaMismatchError, not invalid JSON.
    would_be_schema_error = _validation_error_from_text('{"summary": "ok"}')
    raw = _FakeRawResponse(status="incomplete", parse_exception=would_be_schema_error)
    fake_client = _FakeOpenAIClient(raw_response=raw)
    client = OpenAIReviewClient(settings=_settings(), client=fake_client)

    with pytest.raises(LLMProviderError):
        client.review(DOCUMENT_TEXT)

    assert raw.parse_call_count == 0


# ---------------------------------------------------------------------------
# Invalid JSON vs schema mismatch classification of pydantic.ValidationError
# (only reachable once status == "completed")
# ---------------------------------------------------------------------------


def test_completed_malformed_json_raises_invalid_json_error():
    exc = _validation_error_from_text("this is not valid json at all {{{")
    fake_client = _FakeOpenAIClient(raw_response=_completed_raw_response_raising(exc))
    client = OpenAIReviewClient(settings=_settings(), client=fake_client)

    with pytest.raises(LLMInvalidJSONError):
        client.review(DOCUMENT_TEXT)


def test_completed_valid_json_violating_schema_raises_schema_mismatch_error():
    bad_schema_json = (
        '{"summary": "ok", "risks": [], "missing_requirements": [], "contradictions": [], '
        '"questions_to_client": [], "acceptance_criteria": [], "confidence": "extreme", '
        '"document_readiness": "ready", "model_needs_review": false}'
    )
    exc = _validation_error_from_text(bad_schema_json)
    fake_client = _FakeOpenAIClient(raw_response=_completed_raw_response_raising(exc))
    client = OpenAIReviewClient(settings=_settings(), client=fake_client)

    with pytest.raises(LLMSchemaMismatchError):
        client.review(DOCUMENT_TEXT)


def test_invalid_json_and_schema_mismatch_are_distinct_categories():
    json_exc = _validation_error_from_text("not json {{{")
    schema_exc = _validation_error_from_text('{"summary": "ok"}')

    fake_json_client = _FakeOpenAIClient(raw_response=_completed_raw_response_raising(json_exc))
    fake_schema_client = _FakeOpenAIClient(raw_response=_completed_raw_response_raising(schema_exc))

    json_client = OpenAIReviewClient(settings=_settings(), client=fake_json_client)
    schema_client = OpenAIReviewClient(settings=_settings(), client=fake_schema_client)

    with pytest.raises(LLMInvalidJSONError):
        json_client.review(DOCUMENT_TEXT)
    with pytest.raises(LLMSchemaMismatchError):
        schema_client.review(DOCUMENT_TEXT)


# ---------------------------------------------------------------------------
# Typed boundary around raw_response.parse(): for a completed response, any
# exception it raises — not just pydantic.ValidationError — must come out of
# review() as a LLMClientError subclass, never as a raw SDK/Python exception
# (TypeError, AttributeError, or any other unexpected OpenAIError).
# ---------------------------------------------------------------------------


def test_completed_response_parse_type_error_raises_provider_error():
    original = TypeError("unexpected internal SDK type error")
    fake_client = _FakeOpenAIClient(raw_response=_completed_raw_response_raising(original))
    client = OpenAIReviewClient(settings=_settings(), client=fake_client)

    with pytest.raises(LLMProviderError) as excinfo:
        client.review(DOCUMENT_TEXT)

    error = excinfo.value
    assert error.__cause__ is original
    assert "unexpected internal SDK type error" not in str(error)


def test_completed_response_parse_attribute_error_raises_provider_error():
    original = AttributeError("'str' object has no attribute 'type'")
    fake_client = _FakeOpenAIClient(raw_response=_completed_raw_response_raising(original))
    client = OpenAIReviewClient(settings=_settings(), client=fake_client)

    with pytest.raises(LLMProviderError) as excinfo:
        client.review(DOCUMENT_TEXT)

    error = excinfo.value
    assert error.__cause__ is original
    assert "'str' object has no attribute 'type'" not in str(error)


def test_completed_response_parse_generic_openai_error_raises_provider_error():
    original = OpenAIError("some unexpected SDK parsing failure")
    fake_client = _FakeOpenAIClient(raw_response=_completed_raw_response_raising(original))
    client = OpenAIReviewClient(settings=_settings(), client=fake_client)

    with pytest.raises(LLMProviderError) as excinfo:
        client.review(DOCUMENT_TEXT)

    error = excinfo.value
    assert error.__cause__ is original
    assert "some unexpected SDK parsing failure" not in str(error)


def test_completed_response_parse_own_llm_client_error_is_not_rewrapped():
    # Defensive boundary: if something inside the controlled parse path ever
    # raises one of our own LLMClientError subclasses directly, it must pass
    # through unchanged rather than being re-wrapped as a generic
    # LLMProviderError (which would lose the more specific category).
    original = LLMSchemaMismatchError("уже классифицированная ошибка")
    fake_client = _FakeOpenAIClient(raw_response=_completed_raw_response_raising(original))
    client = OpenAIReviewClient(settings=_settings(), client=fake_client)

    with pytest.raises(LLMSchemaMismatchError) as excinfo:
        client.review(DOCUMENT_TEXT)

    assert excinfo.value is original


# ---------------------------------------------------------------------------
# Errors never leak the API key or the full document text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exception",
    [
        APITimeoutError(request=_request()),
        APIConnectionError(request=_request()),
        _status_error(503, raw_message="boom"),
        OpenAIError("boom"),
    ],
)
def test_errors_never_include_api_key(exception):
    secret_key = "sk-super-secret-key-value"
    fake_client = _FakeOpenAIClient(exception=exception)
    client = OpenAIReviewClient(settings=_settings(api_key=secret_key), client=fake_client)

    with pytest.raises(Exception) as excinfo:
        client.review(DOCUMENT_TEXT)

    assert secret_key not in str(excinfo.value)


@pytest.mark.parametrize(
    "exception",
    [
        APITimeoutError(request=_request()),
        APIConnectionError(request=_request()),
        _status_error(503, raw_message="boom"),
        OpenAIError("boom"),
    ],
)
def test_errors_never_include_full_document_text(exception):
    fake_client = _FakeOpenAIClient(exception=exception)
    client = OpenAIReviewClient(settings=_settings(), client=fake_client)

    with pytest.raises(Exception) as excinfo:
        client.review(DOCUMENT_TEXT)

    assert DOCUMENT_TEXT not in str(excinfo.value)


# ---------------------------------------------------------------------------
# Offline regression tests against the real openai==2.53.0 SDK, using
# httpx.MockTransport so no network call is ever made. These exercise the
# actual `with_raw_response.parse(...)` / `.parse()` split against realistic
# Responses API payloads, reproducing the exact Codex finding: an
# incomplete response whose partial output_text would otherwise be
# misclassified as an invalid-JSON or schema-mismatch failure.
# ---------------------------------------------------------------------------


def _incomplete_envelope(output_text: str) -> dict:
    return {
        "id": "resp_test_incomplete",
        "object": "response",
        "created_at": 1234567890,
        "status": "incomplete",
        "error": None,
        "incomplete_details": {"reason": "max_output_tokens"},
        "instructions": None,
        "model": "gpt-test-model",
        "output": [
            {
                "id": "msg_1",
                "type": "message",
                "status": "incomplete",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": output_text, "annotations": []},
                ],
            }
        ],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "top_p": 1.0,
        "temperature": 1.0,
    }


def _real_client_for_payload(payload: dict, *, api_key: str = "sk-test-offline-key", **client_kwargs) -> OpenAI:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAI(api_key=api_key, http_client=http_client, **client_kwargs)


def test_real_sdk_incomplete_response_with_malformed_partial_json_raises_provider_error():
    payload = _incomplete_envelope('{"summary": "The document describes a notification')  # truncated, malformed
    real_client = _real_client_for_payload(payload)
    client = OpenAIReviewClient(settings=_settings(), client=real_client)

    with pytest.raises(LLMProviderError):
        client.review(DOCUMENT_TEXT)


def test_real_sdk_incomplete_response_with_schema_invalid_partial_json_raises_provider_error():
    payload = _incomplete_envelope('{"summary": "The document describes a notification feature."}')  # valid JSON, incomplete schema
    real_client = _real_client_for_payload(payload)
    client = OpenAIReviewClient(settings=_settings(), client=real_client)

    with pytest.raises(LLMProviderError):
        client.review(DOCUMENT_TEXT)


# ---------------------------------------------------------------------------
# Offline regression test for the second Codex finding: a structurally
# malformed *completed* envelope must not let a raw SDK/Python exception
# (AttributeError, TypeError, APIResponseValidationError, ...) escape
# review(). `output` must be a list per the Responses API schema; a string
# here makes the SDK's own Structured Outputs post-parser fail while
# iterating it.
# ---------------------------------------------------------------------------


def _malformed_completed_envelope() -> dict:
    return {
        "id": "resp_test_malformed_completed",
        "object": "response",
        "created_at": 1234567890,
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "model": "gpt-test-model",
        "output": "this-should-be-a-list-not-a-string",
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "top_p": 1.0,
        "temperature": 1.0,
    }


def test_real_sdk_completed_malformed_envelope_raises_provider_error_without_leaking():
    # Uses the exact client configuration OpenAIReviewClient uses in
    # production (default, non-strict response validation). Under that
    # configuration the SDK's post-parser raises a raw AttributeError while
    # iterating the malformed `output` field.
    secret_key = "sk-test-offline-key-should-not-leak"
    payload = _malformed_completed_envelope()
    real_client = _real_client_for_payload(payload, api_key=secret_key)
    client = OpenAIReviewClient(settings=_settings(), client=real_client)

    with pytest.raises(LLMProviderError) as excinfo:
        client.review(DOCUMENT_TEXT)

    error = excinfo.value
    assert isinstance(error, LLMClientError)
    assert isinstance(error.__cause__, AttributeError)

    surfaces = " ".join([str(error), repr(error), str(error.args), str(vars(error))])
    assert secret_key not in surfaces
    assert "authorization" not in surfaces.lower()
    assert "this-should-be-a-list-not-a-string" not in surfaces
    assert "api.openai.com" not in surfaces

    assert not hasattr(error, "body")
    assert not hasattr(error, "request")
    assert not hasattr(error, "response")


def test_real_sdk_completed_malformed_envelope_with_strict_validation_raises_provider_error():
    # Same malformed envelope, but with the SDK's official
    # `_strict_response_validation=True` client option — a separate,
    # test-only OpenAI client; production client configuration in
    # client.py is unchanged. Under strict validation the SDK raises
    # `openai.APIResponseValidationError` instead of AttributeError, and
    # that must map to LLMProviderError too.
    payload = _malformed_completed_envelope()
    real_client = _real_client_for_payload(payload, _strict_response_validation=True)
    client = OpenAIReviewClient(settings=_settings(), client=real_client)

    with pytest.raises(LLMProviderError) as excinfo:
        client.review(DOCUMENT_TEXT)

    assert isinstance(excinfo.value.__cause__, APIResponseValidationError)

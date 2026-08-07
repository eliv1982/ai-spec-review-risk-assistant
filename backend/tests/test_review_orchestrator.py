"""Offline unit tests for the review orchestration layer
(backend/app/services/review_orchestrator.py).

No test here touches the network, the real `OpenAI` SDK, or `OPENAI_API_KEY`:
the LLM client is always an injected fake satisfying `ReviewClient`.
"""

from typing import List, Optional

import pytest
from pydantic import ValidationError

from app.enums import LLMErrorCategory, ReviewReasonCode
from app.llm.errors import (
    LLMAPIError,
    LLMClientError,
    LLMConfigurationError,
    LLMInvalidJSONError,
    LLMProviderError,
    LLMSchemaMismatchError,
    LLMTransportError,
)
from app.schemas.review import FinalReview, ModelReviewDraft
from app.services.review_qc import build_fallback_review, build_final_review
from app.services.review_orchestrator import ReviewOrchestrationResult, ReviewOrchestrator
import app.services.review_orchestrator as orchestrator_module

NON_VAGUE_TEXT = (
    "The system shall allow an authenticated administrator to configure "
    "notification delivery preferences, including channel selection, retry "
    "policy, and retention period, and every configuration change must be "
    "recorded in an audit log entry that is visible to operators within the "
    "administration panel for later review and compliance reporting purposes."
)

VAGUE_TEXT = "Too short."

DANGEROUS_ERROR_TEXT = (
    'API key sk-test-secret leaked; Authorization: Bearer secret used; '
    'raw-provider-body {"secret": "leak"} returned; req-secret-id'
)


class _UnknownLLMError(LLMClientError):
    """Test-only subclass simulating a future, unmapped `LLMClientError` type.

    Exercises the classifier's safe default (PROVIDER_ERROR) for any
    `LLMClientError` that isn't one of the six explicitly mapped subclasses.
    """


VALID_DRAFT_KWARGS = dict(
    summary="Summary of the reviewed specification.",
    risks=[],
    missing_requirements=[],
    contradictions=[],
    questions_to_client=["Question one?", "Question two?", "Question three?"],
    acceptance_criteria=["Given X, when Y, then Z."],
    confidence="high",
    document_readiness="ready",
    model_needs_review=False,
)


def _clean_draft(**overrides) -> ModelReviewDraft:
    base = dict(VALID_DRAFT_KWARGS)
    base.update(overrides)
    return ModelReviewDraft(**base)


def _sample_final_review() -> FinalReview:
    return build_final_review(original_text=NON_VAGUE_TEXT, draft=_clean_draft())


class _FakeReviewClient:
    """Injected fake satisfying `ReviewClient`; never touches HTTP or the SDK."""

    def __init__(self, *, draft: Optional[ModelReviewDraft] = None, exception: Optional[Exception] = None) -> None:
        self._draft = draft
        self._exception = exception
        self.calls: List[str] = []

    def review(self, document_text: str) -> ModelReviewDraft:
        self.calls.append(document_text)
        if self._exception is not None:
            raise self._exception
        assert self._draft is not None
        return self._draft


FALLBACK_CATEGORY_CASES = [
    pytest.param(
        LLMConfigurationError("ошибка конфигурации"),
        LLMErrorCategory.CONFIGURATION_ERROR,
        ReviewReasonCode.MODEL_ERROR,
        id="configuration",
    ),
    pytest.param(
        LLMTransportError("ошибка транспорта"),
        LLMErrorCategory.TRANSPORT_ERROR,
        ReviewReasonCode.MODEL_ERROR,
        id="transport",
    ),
    pytest.param(
        LLMAPIError("ошибка api", status_code=500, request_id="req-1"),
        LLMErrorCategory.API_ERROR,
        ReviewReasonCode.MODEL_ERROR,
        id="api",
    ),
    pytest.param(
        LLMInvalidJSONError("невалидный json"),
        LLMErrorCategory.INVALID_JSON,
        ReviewReasonCode.INVALID_JSON,
        id="invalid_json",
    ),
    pytest.param(
        LLMSchemaMismatchError("схема не совпадает"),
        LLMErrorCategory.SCHEMA_MISMATCH,
        ReviewReasonCode.SCHEMA_MISMATCH,
        id="schema_mismatch",
    ),
    pytest.param(
        LLMProviderError("ошибка провайдера"),
        LLMErrorCategory.PROVIDER_ERROR,
        ReviewReasonCode.MODEL_ERROR,
        id="provider",
    ),
]


# ---------------------------------------------------------------------------
# Success / happy path
# ---------------------------------------------------------------------------


def test_success_path_calls_llm_client_exactly_once_with_exact_text():
    fake = _FakeReviewClient(draft=_clean_draft())
    orchestrator = ReviewOrchestrator(llm_client=fake)

    orchestrator.review(NON_VAGUE_TEXT)

    assert fake.calls == [NON_VAGUE_TEXT]


def test_success_path_returns_qc_output_unchanged():
    draft = _clean_draft()
    fake = _FakeReviewClient(draft=draft)
    orchestrator = ReviewOrchestrator(llm_client=fake)

    result = orchestrator.review(NON_VAGUE_TEXT)
    expected = build_final_review(original_text=NON_VAGUE_TEXT, draft=draft)

    assert isinstance(result, ReviewOrchestrationResult)
    assert result.final_review == expected
    assert result.used_fallback is False
    assert result.llm_error_category is None


def test_success_path_reason_codes_and_needs_review_match_qc_exactly():
    draft = _clean_draft(acceptance_criteria=[])
    fake = _FakeReviewClient(draft=draft)
    orchestrator = ReviewOrchestrator(llm_client=fake)

    result = orchestrator.review(NON_VAGUE_TEXT)

    assert result.final_review.needs_review is True
    assert result.final_review.review_reason_codes == [ReviewReasonCode.MISSING_ACCEPTANCE_CRITERIA]


def test_success_path_does_not_mutate_draft_before_qc():
    draft = _clean_draft(confidence="low")
    snapshot_before = draft.model_dump()
    fake = _FakeReviewClient(draft=draft)
    orchestrator = ReviewOrchestrator(llm_client=fake)

    orchestrator.review(NON_VAGUE_TEXT)

    assert draft.model_dump() == snapshot_before


# ---------------------------------------------------------------------------
# Fallback path, parametrized over every LLMClientError category
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("exc,expected_category,expected_root_code", FALLBACK_CATEGORY_CASES)
def test_fallback_path_per_category(exc, expected_category, expected_root_code):
    fake = _FakeReviewClient(exception=exc)
    orchestrator = ReviewOrchestrator(llm_client=fake)

    result = orchestrator.review(NON_VAGUE_TEXT)
    expected_final_review = build_fallback_review(original_text=NON_VAGUE_TEXT, root_reason_code=expected_root_code)

    assert fake.calls == [NON_VAGUE_TEXT]
    assert result.used_fallback is True
    assert result.llm_error_category == expected_category
    assert result.final_review == expected_final_review
    assert result.final_review.needs_review is True
    assert expected_root_code in result.final_review.review_reason_codes


@pytest.mark.parametrize("exc,expected_category,expected_root_code", FALLBACK_CATEGORY_CASES)
def test_fallback_error_category_is_never_a_reason_code_instance(exc, expected_category, expected_root_code):
    fake = _FakeReviewClient(exception=exc)
    orchestrator = ReviewOrchestrator(llm_client=fake)

    result = orchestrator.review(NON_VAGUE_TEXT)

    assert all(isinstance(code, ReviewReasonCode) for code in result.final_review.review_reason_codes)
    assert not any(isinstance(code, LLMErrorCategory) for code in result.final_review.review_reason_codes)


@pytest.mark.parametrize("exc,expected_category,expected_root_code", FALLBACK_CATEGORY_CASES)
def test_fallback_original_exception_not_stored_on_result(exc, expected_category, expected_root_code):
    fake = _FakeReviewClient(exception=exc)
    orchestrator = ReviewOrchestrator(llm_client=fake)

    result = orchestrator.review(NON_VAGUE_TEXT)

    for value in vars(result).values():
        assert not isinstance(value, BaseException)
    assert not isinstance(result.final_review, BaseException)


def test_fallback_uses_approved_russian_safe_texts():
    fake = _FakeReviewClient(exception=LLMProviderError("ошибка провайдера"))
    orchestrator = ReviewOrchestrator(llm_client=fake)

    result = orchestrator.review(NON_VAGUE_TEXT)

    assert result.final_review.summary == (
        "Автоматическая проверка не может быть выполнена надёжно. Требуется ручная проверка."
    )
    assert result.final_review.questions_to_client == [
        "Можете ли вы предоставить более полный и конкретный документ с требованиями?"
    ]


def test_fallback_result_does_not_embed_full_document_text():
    distinctive_text = "DISTINCTIVE-MARKER-9f3d2a. " + NON_VAGUE_TEXT
    fake = _FakeReviewClient(exception=LLMProviderError("ошибка провайдера"))
    orchestrator = ReviewOrchestrator(llm_client=fake)

    result = orchestrator.review(distinctive_text)

    haystacks = [
        str(result),
        repr(result),
        str(result.model_dump()),
        str(result.model_dump(mode="json")),
    ]
    for haystack in haystacks:
        assert "DISTINCTIVE-MARKER-9f3d2a" not in haystack


# ---------------------------------------------------------------------------
# Unmapped LLMClientError instances still produce the safe default category
# ---------------------------------------------------------------------------


def test_direct_llm_client_error_instance_maps_to_provider_error_and_model_error():
    fake = _FakeReviewClient(exception=LLMClientError("опасный текст"))
    orchestrator = ReviewOrchestrator(llm_client=fake)

    result = orchestrator.review(NON_VAGUE_TEXT)

    assert result.used_fallback is True
    assert result.llm_error_category == LLMErrorCategory.PROVIDER_ERROR
    assert result.final_review.review_reason_codes == [ReviewReasonCode.MODEL_ERROR]
    assert "опасный текст" not in str(result.model_dump())


def test_unknown_llm_client_error_subclass_maps_to_provider_error_and_model_error():
    fake = _FakeReviewClient(exception=_UnknownLLMError("опасный текст неизвестного подкласса"))
    orchestrator = ReviewOrchestrator(llm_client=fake)

    result = orchestrator.review(NON_VAGUE_TEXT)

    assert result.used_fallback is True
    assert result.llm_error_category == LLMErrorCategory.PROVIDER_ERROR
    assert result.final_review.review_reason_codes == [ReviewReasonCode.MODEL_ERROR]
    assert "опасный текст неизвестного подкласса" not in str(result.model_dump())


# ---------------------------------------------------------------------------
# Vague vs. non-vague fallback input: TOO_VAGUE_INPUT is appended only when
# the original text independently fails the QC vagueness threshold, and only
# by the existing fallback factory — never by the orchestrator itself.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("exc,expected_category,expected_root_code", FALLBACK_CATEGORY_CASES)
def test_fallback_with_vague_input_appends_too_vague_in_catalogue_order(exc, expected_category, expected_root_code):
    fake = _FakeReviewClient(exception=exc)
    orchestrator = ReviewOrchestrator(llm_client=fake)

    result = orchestrator.review(VAGUE_TEXT)
    expected_final_review = build_fallback_review(original_text=VAGUE_TEXT, root_reason_code=expected_root_code)

    assert result.used_fallback is True
    assert result.final_review == expected_final_review
    assert result.final_review.needs_review is True
    # Catalogue order (REVIEW_SCHEMA.md): TOO_VAGUE_INPUT (2) always precedes
    # every technical root code (6-8).
    assert result.final_review.review_reason_codes == [ReviewReasonCode.TOO_VAGUE_INPUT, expected_root_code]
    assert result.final_review.summary == (
        "Автоматическая проверка не может быть выполнена надёжно. Требуется ручная проверка."
    )
    assert result.final_review.questions_to_client == [
        "Можете ли вы предоставить более полный и конкретный документ с требованиями?"
    ]


@pytest.mark.parametrize("exc,expected_category,expected_root_code", FALLBACK_CATEGORY_CASES)
def test_fallback_with_non_vague_input_omits_too_vague(exc, expected_category, expected_root_code):
    fake = _FakeReviewClient(exception=exc)
    orchestrator = ReviewOrchestrator(llm_client=fake)

    result = orchestrator.review(NON_VAGUE_TEXT)

    assert result.final_review.review_reason_codes == [expected_root_code]
    assert ReviewReasonCode.TOO_VAGUE_INPUT not in result.final_review.review_reason_codes


# ---------------------------------------------------------------------------
# Errors that must NOT be turned into a fallback
# ---------------------------------------------------------------------------


def test_generic_exception_from_llm_client_propagates():
    fake = _FakeReviewClient(exception=RuntimeError("boom"))
    orchestrator = ReviewOrchestrator(llm_client=fake)

    with pytest.raises(RuntimeError, match="boom"):
        orchestrator.review(NON_VAGUE_TEXT)


def test_qc_error_propagates(monkeypatch):
    def _boom(*, original_text, draft):
        raise RuntimeError("qc exploded")

    monkeypatch.setattr(orchestrator_module, "build_final_review", _boom)

    fake = _FakeReviewClient(draft=_clean_draft())
    orchestrator = ReviewOrchestrator(llm_client=fake)

    with pytest.raises(RuntimeError, match="qc exploded"):
        orchestrator.review(NON_VAGUE_TEXT)


def test_fallback_factory_error_propagates(monkeypatch):
    def _boom(*, original_text, root_reason_code):
        raise RuntimeError("fallback factory exploded")

    monkeypatch.setattr(orchestrator_module, "build_fallback_review", _boom)

    fake = _FakeReviewClient(exception=LLMProviderError("ошибка провайдера"))
    orchestrator = ReviewOrchestrator(llm_client=fake)

    with pytest.raises(RuntimeError, match="fallback factory exploded"):
        orchestrator.review(NON_VAGUE_TEXT)


def test_mapper_error_propagates_without_a_second_fallback_attempt(monkeypatch):
    mapper_error = RuntimeError("mapper exploded")

    def _boom(exc):
        raise mapper_error

    monkeypatch.setattr(orchestrator_module, "_classify_llm_error", _boom)

    fallback_calls: list = []

    def _fallback_spy(*, original_text, root_reason_code):
        fallback_calls.append((original_text, root_reason_code))
        raise AssertionError("build_fallback_review must not run once the mapper has failed")

    monkeypatch.setattr(orchestrator_module, "build_fallback_review", _fallback_spy)

    fake = _FakeReviewClient(exception=LLMProviderError("ошибка провайдера"))
    orchestrator = ReviewOrchestrator(llm_client=fake)

    with pytest.raises(RuntimeError) as exc_info:
        orchestrator.review(NON_VAGUE_TEXT)

    assert exc_info.value is mapper_error
    assert fallback_calls == []


def test_keyboard_interrupt_is_not_caught():
    fake = _FakeReviewClient(exception=KeyboardInterrupt())
    orchestrator = ReviewOrchestrator(llm_client=fake)

    with pytest.raises(KeyboardInterrupt):
        orchestrator.review(NON_VAGUE_TEXT)


def test_system_exit_is_not_caught():
    fake = _FakeReviewClient(exception=SystemExit())
    orchestrator = ReviewOrchestrator(llm_client=fake)

    with pytest.raises(SystemExit):
        orchestrator.review(NON_VAGUE_TEXT)


# ---------------------------------------------------------------------------
# Safety: no exception content, secrets, or full document text leak into the result
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        LLMConfigurationError(DANGEROUS_ERROR_TEXT),
        LLMTransportError(DANGEROUS_ERROR_TEXT),
        LLMAPIError(DANGEROUS_ERROR_TEXT, status_code=500, request_id="req-secret-id"),
        LLMInvalidJSONError(DANGEROUS_ERROR_TEXT),
        LLMSchemaMismatchError(DANGEROUS_ERROR_TEXT),
        LLMProviderError(DANGEROUS_ERROR_TEXT),
    ],
    ids=["configuration", "transport", "api", "invalid_json", "schema_mismatch", "provider"],
)
def test_dangerous_exception_text_never_leaks_into_result(exc):
    fake = _FakeReviewClient(exception=exc)
    orchestrator = ReviewOrchestrator(llm_client=fake)

    result = orchestrator.review(NON_VAGUE_TEXT)

    forbidden_snippets = [
        "API key",
        "sk-test-secret",
        "Authorization: Bearer secret",
        "raw-provider-body",
        "req-secret-id",
    ]
    haystacks = [
        str(result),
        repr(result),
        str(result.model_dump()),
        str(result.model_dump(mode="json")),
    ]
    for haystack in haystacks:
        for snippet in forbidden_snippets:
            assert snippet not in haystack


# ---------------------------------------------------------------------------
# Model contract: ReviewOrchestrationResult
# ---------------------------------------------------------------------------


def test_result_forbids_additional_fields():
    with pytest.raises(ValidationError):
        ReviewOrchestrationResult(
            final_review=_sample_final_review(),
            used_fallback=False,
            llm_error_category=None,
            unexpected_field="nope",
        )


@pytest.mark.parametrize("coerced_value", [1, 0, "true", "false", "1", "0"])
def test_used_fallback_rejects_non_strict_bool_coercions(coerced_value):
    with pytest.raises(ValidationError):
        ReviewOrchestrationResult(
            final_review=_sample_final_review(),
            used_fallback=coerced_value,
            llm_error_category=None,
        )


def test_used_fallback_accepts_real_bool_with_consistent_category():
    success_result = ReviewOrchestrationResult(
        final_review=_sample_final_review(),
        used_fallback=False,
        llm_error_category=None,
    )
    assert success_result.used_fallback is False

    fallback_result = ReviewOrchestrationResult(
        final_review=_sample_final_review(),
        used_fallback=True,
        llm_error_category=LLMErrorCategory.PROVIDER_ERROR,
    )
    assert fallback_result.used_fallback is True


def test_llm_error_category_is_closed_enum():
    with pytest.raises(ValidationError):
        ReviewOrchestrationResult(
            final_review=_sample_final_review(),
            used_fallback=True,
            llm_error_category="NOT_A_REAL_CATEGORY",
        )


def test_success_result_cannot_carry_error_category():
    with pytest.raises(ValidationError):
        ReviewOrchestrationResult(
            final_review=_sample_final_review(),
            used_fallback=False,
            llm_error_category=LLMErrorCategory.PROVIDER_ERROR,
        )


def test_fallback_result_requires_error_category():
    with pytest.raises(ValidationError):
        ReviewOrchestrationResult(
            final_review=_sample_final_review(),
            used_fallback=True,
            llm_error_category=None,
        )


# ---------------------------------------------------------------------------
# ReviewOrchestrationResult is a frozen value object: no field may be
# reassigned after construction, so a later persistence/audit layer cannot
# alter what QC already decided.
# ---------------------------------------------------------------------------


def _sample_success_result() -> ReviewOrchestrationResult:
    return ReviewOrchestrationResult(
        final_review=_sample_final_review(),
        used_fallback=False,
        llm_error_category=None,
    )


def test_result_rejects_reassigning_used_fallback():
    result = _sample_success_result()
    with pytest.raises(ValidationError):
        result.used_fallback = True


def test_result_rejects_reassigning_llm_error_category():
    result = _sample_success_result()
    with pytest.raises(ValidationError):
        result.llm_error_category = LLMErrorCategory.PROVIDER_ERROR


def test_result_rejects_reassigning_final_review():
    result = _sample_success_result()
    with pytest.raises(ValidationError):
        result.final_review = _sample_final_review()

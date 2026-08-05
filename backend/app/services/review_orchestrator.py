"""Review orchestration layer (application/service layer, not an API endpoint).

Wires an injected LLM review client to the deterministic QC layer
(`app.services.review_qc`):

    document text -> LLM client -> ModelReviewDraft -> deterministic QC -> FinalReview

On a typed `LLMClientError`, the orchestrator classifies the failure into a
stable `LLMErrorCategory` and builds the safe fallback via the existing
`build_fallback_review(...)` factory. That factory already implements the
full deterministic "Safe FinalReview fallback" construction documented in
REVIEW_SCHEMA.md (fixed safe content, plus the same `is_too_vague` rule used
by `build_final_review`) and returns a `FinalReview` directly — this
codebase's QC layer has no separate "fallback ModelReviewDraft" step to feed
back through `build_final_review`, so none is fabricated here. Content,
reason codes, and thresholds all stay exclusively owned by
`app.services.review_qc`; this module only decides *which* of the three
technical root reason codes (MODEL_ERROR / INVALID_JSON / SCHEMA_MISMATCH)
applies, mirroring ARCHITECTURE.md's failure-handling table.

Only `LLMClientError` is caught. Any other exception (a programming error, an
unexpected failure inside the LLM client, QC, or the fallback factory,
`KeyboardInterrupt`, `SystemExit`) propagates unchanged: fallback is reserved
for already-typed provider/LLM failures, never used to paper over arbitrary
bugs.

Out of scope here: persistence, repositories, audit, HTTP endpoints, retries,
a second LLM call, or a fallback model — see backend/README.md.
"""

from typing import Optional, Protocol

from pydantic import BaseModel, ConfigDict, StrictBool, model_validator

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


class ReviewClient(Protocol):
    """Minimal surface the orchestrator needs from an LLM review client.

    Structurally satisfied by `app.llm.client.OpenAIReviewClient` and by any
    offline test double; the orchestrator never imports the OpenAI SDK.
    """

    def review(self, document_text: str) -> ModelReviewDraft: ...


_ERROR_CATEGORY_BY_EXCEPTION_TYPE: dict[type, LLMErrorCategory] = {
    LLMConfigurationError: LLMErrorCategory.CONFIGURATION_ERROR,
    LLMTransportError: LLMErrorCategory.TRANSPORT_ERROR,
    LLMAPIError: LLMErrorCategory.API_ERROR,
    LLMInvalidJSONError: LLMErrorCategory.INVALID_JSON,
    LLMSchemaMismatchError: LLMErrorCategory.SCHEMA_MISMATCH,
    LLMProviderError: LLMErrorCategory.PROVIDER_ERROR,
}

# ARCHITECTURE.md ("Failure handling") / REVIEW_SCHEMA.md ("Failure-only
# reason codes and safe fallback"): every provider/API/transport/model-call
# failure is rooted as MODEL_ERROR; only JSON-decode and schema-validation
# failures get their own root code.
_ROOT_REASON_CODE_BY_CATEGORY: dict[LLMErrorCategory, ReviewReasonCode] = {
    LLMErrorCategory.CONFIGURATION_ERROR: ReviewReasonCode.MODEL_ERROR,
    LLMErrorCategory.TRANSPORT_ERROR: ReviewReasonCode.MODEL_ERROR,
    LLMErrorCategory.API_ERROR: ReviewReasonCode.MODEL_ERROR,
    LLMErrorCategory.PROVIDER_ERROR: ReviewReasonCode.MODEL_ERROR,
    LLMErrorCategory.INVALID_JSON: ReviewReasonCode.INVALID_JSON,
    LLMErrorCategory.SCHEMA_MISMATCH: ReviewReasonCode.SCHEMA_MISMATCH,
}


def _classify_llm_error(exc: LLMClientError) -> LLMErrorCategory:
    for exc_type, category in _ERROR_CATEGORY_BY_EXCEPTION_TYPE.items():
        if isinstance(exc, exc_type):
            return category
    return LLMErrorCategory.PROVIDER_ERROR


class ReviewOrchestrationResult(BaseModel):
    """Orchestration outcome handed to the next persistence/audit layer.

    Carries only the already-QC'd `FinalReview` plus safe metadata — never the
    original exception, `str(exc)`, a stack trace, a provider response, an API
    key/authorization header, or the full document text.

    Frozen: this is a completed value object, not a mutable working buffer —
    a later persistence/audit layer must not be able to alter what QC already
    decided by assigning over `final_review`, `used_fallback`, or
    `llm_error_category` after the fact.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    final_review: FinalReview
    used_fallback: StrictBool
    llm_error_category: Optional[LLMErrorCategory] = None

    @model_validator(mode="after")
    def _check_error_category_matches_fallback_flag(self) -> "ReviewOrchestrationResult":
        if self.used_fallback and self.llm_error_category is None:
            raise ValueError("llm_error_category is required when used_fallback is True")
        if not self.used_fallback and self.llm_error_category is not None:
            raise ValueError("llm_error_category must be None when used_fallback is False")
        return self


class ReviewOrchestrator:
    """Application-layer service composing the LLM client and deterministic QC.

    Not responsible for persistence, transactions, audit, HTTP, retries, or a
    second LLM/fallback-model call.
    """

    def __init__(self, *, llm_client: ReviewClient) -> None:
        self._llm_client = llm_client

    def review(self, document_text: str) -> ReviewOrchestrationResult:
        try:
            draft = self._llm_client.review(document_text)
        except LLMClientError as exc:
            return self._build_fallback_result(document_text, exc)

        final_review = build_final_review(original_text=document_text, draft=draft)
        return ReviewOrchestrationResult(
            final_review=final_review,
            used_fallback=False,
            llm_error_category=None,
        )

    def _build_fallback_result(self, document_text: str, exc: LLMClientError) -> ReviewOrchestrationResult:
        category = _classify_llm_error(exc)
        root_reason_code = _ROOT_REASON_CODE_BY_CATEGORY[category]
        final_review = build_fallback_review(original_text=document_text, root_reason_code=root_reason_code)
        return ReviewOrchestrationResult(
            final_review=final_review,
            used_fallback=True,
            llm_error_category=category,
        )

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from app.enums import (
    ReviewConfidence,
    ReviewReadiness,
    ReviewReasonCode,
    RiskCategory,
    RiskSeverity,
)
from app.models import Review as ReviewModel


def _require_trimmed(value: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("значение не может быть пустым после удаления пробелов")
    return trimmed


class Risk(BaseModel):
    """Nested risk item shared by ModelReviewDraft and FinalReview (REVIEW_SCHEMA.md)."""

    model_config = ConfigDict(extra="forbid")

    severity: RiskSeverity
    category: RiskCategory
    description: str
    evidence: Optional[str]

    @field_validator("description", mode="after")
    @classmethod
    def _validate_description(cls, value: str) -> str:
        return _require_trimmed(value)

    @field_validator("evidence", mode="after")
    @classmethod
    def _validate_evidence(cls, value: Optional[str]) -> Optional[str]:
        return value if value is None else _require_trimmed(value)


class MissingRequirement(BaseModel):
    """Nested missing-requirement item shared by ModelReviewDraft and FinalReview."""

    model_config = ConfigDict(extra="forbid")

    category: RiskCategory
    description: str

    @field_validator("description", mode="after")
    @classmethod
    def _validate_description(cls, value: str) -> str:
        return _require_trimmed(value)


class Contradiction(BaseModel):
    """Nested contradiction item shared by ModelReviewDraft and FinalReview.

    `evidence` is a required array that may itself be empty (non-empty excerpts
    are preferred when available); every string it does contain must be
    trimmed and non-empty.
    """

    model_config = ConfigDict(extra="forbid")

    description: str
    evidence: List[str]

    @field_validator("description", mode="after")
    @classmethod
    def _validate_description(cls, value: str) -> str:
        return _require_trimmed(value)

    @field_validator("evidence", mode="after")
    @classmethod
    def _validate_evidence(cls, value: List[str]) -> List[str]:
        return [_require_trimmed(item) for item in value]


class _ReviewContentBase(BaseModel):
    """Content fields shared by ModelReviewDraft and FinalReview (REVIEW_SCHEMA.md).

    Not instantiated directly. The model-proposed flag (`model_needs_review`)
    and the backend-produced flag/codes (`needs_review` / `review_reason_codes`)
    are declared only on the respective subclasses below, so the inherited
    `extra="forbid"` config rejects either schema from carrying the other's
    flag field(s).
    """

    model_config = ConfigDict(extra="forbid")

    summary: str
    risks: List[Risk]
    missing_requirements: List[MissingRequirement]
    contradictions: List[Contradiction]
    questions_to_client: List[str]
    acceptance_criteria: List[str]
    confidence: ReviewConfidence
    document_readiness: ReviewReadiness

    @field_validator("summary", mode="after")
    @classmethod
    def _validate_summary(cls, value: str) -> str:
        return _require_trimmed(value)

    @field_validator("questions_to_client", "acceptance_criteria", mode="after")
    @classmethod
    def _validate_string_list(cls, value: List[str]) -> List[str]:
        return [_require_trimmed(item) for item in value]


class ModelReviewDraft(_ReviewContentBase):
    """Untrusted OpenAI Structured Outputs payload, Pydantic-validated before QC.

    Must never be persisted as `reviews.review_json` and never returned by the API.
    """

    model_needs_review: StrictBool


class FinalReview(_ReviewContentBase):
    """Backend-produced object stored in `reviews.review_json` and returned by the API.

    `needs_review` and `review_reason_codes` are written exclusively by the
    backend; the model never proposes, selects, or preserves a reason code.
    """

    needs_review: StrictBool
    review_reason_codes: List[ReviewReasonCode]


class ReviewResponse(BaseModel):
    id: str
    created_at: str
    document_id: str
    review_json: Dict[str, Any]
    confidence: ReviewConfidence
    readiness: ReviewReadiness
    needs_review: bool
    reason_codes: List[str]
    error: Optional[str] = None

    @classmethod
    def from_model(cls, review: ReviewModel) -> "ReviewResponse":
        return cls(
            id=review.id,
            created_at=review.created_at,
            document_id=review.document_id,
            review_json=review.review_json,
            confidence=review.confidence,
            readiness=review.readiness,
            needs_review=bool(review.needs_review),
            reason_codes=review.reason_codes_json,
            error=review.error,
        )


def _drop_default(schema: Dict[str, Any]) -> None:
    """`json_schema_extra` hook for `AIReviewRequest.title`: removes the stray
    `"default": null` Pydantic would otherwise publish for a `str`-typed field
    whose Python default is `None`. Mutates only the schema dict generated for
    this one field; never touches runtime validation."""
    schema.pop("default", None)


class AIReviewRequest(BaseModel):
    """Request body for `POST /api/ai/review` (API_CONTRACTS.md).

    Stateless: `title` is an optional audit-context label only and is never
    persisted as a `Document`. `text` is passed verbatim (after trim) to
    `ReviewOrchestrator.review()`.

    `title` may be omitted entirely (defaults to `None`), but an explicit JSON
    `null` is rejected with a 422: a caller that wants "no title" must omit the
    key, not send `null`. Declaring the field as plain `str` (not `Optional[str]`)
    with a `None` default keeps the OpenAPI schema showing `{"type": "string"}`
    instead of a `string | null` union — the field still isn't in `required`, so
    omission remains valid — while the `mode="before"` validator below rejects an
    explicit `null` with a Russian message before Pydantic's own (English) type
    check would otherwise fire.

    A bare `Field(default=None)` would still publish `"default": null` in the
    OpenAPI schema for this field, which a generated client could read as
    license to send `null` even though runtime rejects it. `json_schema_extra`
    as a callable (Pydantic v2) runs only for this field's generated schema
    dict and only at schema-build time — never at validation time — so it can
    drop that stray `"default": null` without touching the field's actual
    runtime default or any other model's schema.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(default=None, json_schema_extra=_drop_default)
    text: str

    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_null_title(cls, data: Any) -> Any:
        if isinstance(data, dict) and "title" in data and data["title"] is None:
            raise ValueError(
                "title не может быть null; чтобы не указывать заголовок, опустите поле полностью"
            )
        return data

    @field_validator("title", mode="after")
    @classmethod
    def _validate_title(cls, value: Optional[str]) -> Optional[str]:
        return value if value is None else _require_trimmed(value)

    @field_validator("text", mode="after")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return _require_trimmed(value)


class AIReviewResponse(BaseModel):
    """Response body for `POST /api/ai/review` (API_CONTRACTS.md).

    Exposes a backend-produced `FinalReview` via `review_json` plus the same
    denormalized top-level fields as a persisted review response, never the raw
    `ModelReviewDraft` and never `model_needs_review`. Unlike `ReviewResponse`,
    carries no `id`/`created_at`/`document_id`: nothing is persisted as a
    `Document` or `Review` row for this stateless endpoint.
    """

    model_config = ConfigDict(extra="forbid")

    review_json: Dict[str, Any]
    confidence: ReviewConfidence
    readiness: ReviewReadiness
    needs_review: bool
    reason_codes: List[str]
    error: Optional[str] = None

    @classmethod
    def from_final_review(cls, final_review: FinalReview) -> "AIReviewResponse":
        return cls(
            review_json=final_review.model_dump(mode="json"),
            confidence=final_review.confidence,
            readiness=final_review.document_readiness,
            needs_review=final_review.needs_review,
            reason_codes=[code.value for code in final_review.review_reason_codes],
            error=None,
        )

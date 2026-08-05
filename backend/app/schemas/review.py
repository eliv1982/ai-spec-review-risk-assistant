from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, StrictBool, field_validator

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

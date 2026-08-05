from enum import Enum


class DocumentStatus(str, Enum):
    created = "created"
    reviewed = "reviewed"
    review_failed = "review_failed"


class ReviewConfidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class ReviewReadiness(str, Enum):
    ready = "ready"
    needs_clarification = "needs_clarification"
    not_ready = "not_ready"


class AuditStatus(str, Enum):
    success = "success"
    needs_review = "needs_review"
    error = "error"


class RiskSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class RiskCategory(str, Enum):
    scope = "scope"
    functionality = "functionality"
    data = "data"
    integration = "integration"
    security = "security"
    privacy = "privacy"
    performance = "performance"
    reliability = "reliability"
    usability = "usability"
    operations = "operations"
    acceptance = "acceptance"
    timeline = "timeline"
    dependency = "dependency"
    compliance = "compliance"
    other = "other"


class ReviewReasonCode(str, Enum):
    """Backend-only reason codes. Declaration order is the required catalogue
    normalization order (REVIEW_SCHEMA.md, "review_reason_codes (catalogue order)")."""

    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    TOO_VAGUE_INPUT = "TOO_VAGUE_INPUT"
    CONTRADICTORY_INPUT = "CONTRADICTORY_INPUT"
    MISSING_ACCEPTANCE_CRITERIA = "MISSING_ACCEPTANCE_CRITERIA"
    INSUFFICIENT_QUESTIONS = "INSUFFICIENT_QUESTIONS"
    INVALID_JSON = "INVALID_JSON"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    MODEL_ERROR = "MODEL_ERROR"


class LLMErrorCategory(str, Enum):
    """Safe, stable technical categories for a typed `app.llm.errors.LLMClientError`
    failure, used as review-orchestration result metadata for a later audit layer.

    Maps 1:1 onto the `LLMClientError` subclasses in `app/llm/errors.py`. Never
    derived from `type(exc).__name__`, an exception message, or model output.
    Distinct from `ReviewReasonCode`: never written into
    `FinalReview.review_reason_codes`.
    """

    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    TRANSPORT_ERROR = "TRANSPORT_ERROR"
    API_ERROR = "API_ERROR"
    INVALID_JSON = "INVALID_JSON"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    PROVIDER_ERROR = "PROVIDER_ERROR"

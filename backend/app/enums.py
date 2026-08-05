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

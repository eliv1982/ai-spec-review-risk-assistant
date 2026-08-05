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

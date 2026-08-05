from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.enums import ReviewConfidence, ReviewReadiness
from app.models import Review as ReviewModel


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

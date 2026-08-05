from typing import Any, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Review


class ReviewRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(
        self,
        *,
        document_id: str,
        review_json: dict[str, Any],
        confidence: str,
        readiness: str,
        needs_review: bool,
        reason_codes: list[str],
        error: Optional[str] = None,
    ) -> Review:
        review = Review(
            document_id=document_id,
            review_json=review_json,
            confidence=confidence,
            readiness=readiness,
            needs_review=int(bool(needs_review)),
            reason_codes_json=list(reason_codes),
            error=error,
        )
        self.db.add(review)
        return review

    def get_by_id(self, review_id: str) -> Optional[Review]:
        return self.db.get(Review, review_id)

    def list(
        self,
        *,
        document_id: Optional[str] = None,
        needs_review: Optional[bool] = None,
        confidence: Optional[str] = None,
        readiness: Optional[str] = None,
        limit: int,
        offset: int,
    ) -> tuple[Sequence[Review], int]:
        filters = []
        if document_id is not None:
            filters.append(Review.document_id == document_id)
        if needs_review is not None:
            filters.append(Review.needs_review == int(needs_review))
        if confidence is not None:
            filters.append(Review.confidence == confidence)
        if readiness is not None:
            filters.append(Review.readiness == readiness)

        total = self.db.scalar(select(func.count()).select_from(Review).where(*filters)) or 0

        stmt = (
            select(Review)
            .where(*filters)
            .order_by(Review.created_at.desc(), Review.id.desc())
            .limit(limit)
            .offset(offset)
        )
        items = self.db.scalars(stmt).all()
        return items, total

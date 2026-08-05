from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.enums import ReviewConfidence, ReviewReadiness
from app.repositories.review_repository import ReviewRepository
from app.schemas.common import PaginatedResponse
from app.schemas.review import ReviewResponse

router = APIRouter()


@router.get("", response_model=PaginatedResponse[ReviewResponse])
def list_reviews(
    document_id: Optional[UUID] = Query(default=None),
    needs_review: Optional[bool] = Query(default=None),
    confidence: Optional[ReviewConfidence] = Query(default=None),
    readiness: Optional[ReviewReadiness] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> PaginatedResponse[ReviewResponse]:
    repo = ReviewRepository(db)
    items, total = repo.list(
        document_id=str(document_id) if document_id is not None else None,
        needs_review=needs_review,
        confidence=confidence.value if confidence is not None else None,
        readiness=readiness.value if readiness is not None else None,
        limit=limit,
        offset=offset,
    )
    return PaginatedResponse(
        items=[ReviewResponse.from_model(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{review_id}", response_model=ReviewResponse)
def get_review(review_id: UUID, db: Session = Depends(get_db)) -> ReviewResponse:
    repo = ReviewRepository(db)
    review = repo.get_by_id(str(review_id))
    if review is None:
        raise HTTPException(status_code=404, detail="Проверка не найдена")
    return ReviewResponse.from_model(review)

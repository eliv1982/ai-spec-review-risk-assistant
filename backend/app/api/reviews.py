from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.enums import ReviewConfidence, ReviewReadiness
from app.repositories.document_repository import DocumentRepository
from app.repositories.review_repository import ReviewRepository
from app.schemas.common import PaginatedResponse
from app.schemas.review import ReviewResponse
from app.services.csv_export import build_csv_response, serialize_json_cell

router = APIRouter()

REASON_CODE_DELIMITER = "|"


def _bool_cell(value: bool) -> str:
    return "true" if value else "false"


def _none_to_empty(value: Optional[str]) -> str:
    return value if value is not None else ""


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


# Registered before `/{review_id}` so a static `/export` path segment is never
# swallowed by the dynamic UUID route (FastAPI/Starlette matches routes in
# registration order — `/{review_id}` would otherwise match `/export` first,
# with `review_id="export"`, and fail UUID parsing with a 422 instead of
# reaching this handler).
#
# `response_class=Response` clears FastAPI's default `application/json`
# media type (its `media_type` is `None`, unlike `JSONResponse`), and
# `responses={200: {...}}` then documents the actual `text/csv` body —
# without both, OpenAPI would document a JSON response even though this
# handler always returns a `text/csv` `Response`.
@router.get(
    "/export",
    response_class=Response,
    responses={
        200: {
            "description": "CSV-файл со списком проверок",
            "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
def export_reviews(
    document_id: Optional[UUID] = Query(default=None),
    needs_review: Optional[bool] = Query(default=None),
    confidence: Optional[ReviewConfidence] = Query(default=None),
    readiness: Optional[ReviewReadiness] = Query(default=None),
    db: Session = Depends(get_db),
) -> Response:
    repo = ReviewRepository(db)
    items = repo.list_all_for_export(
        document_id=str(document_id) if document_id is not None else None,
        needs_review=needs_review,
        confidence=confidence.value if confidence is not None else None,
        readiness=readiness.value if readiness is not None else None,
    )

    rows: list[list[str]] = [
        [
            "ID проверки",
            "ID документа",
            "Название документа",
            "Дата создания",
            "Требуется ручная проверка",
            "Уверенность",
            "Готовность документа",
            "Коды причин",
            "Ошибка",
        ]
    ]
    for review in items:
        rows.append(
            [
                review.id,
                review.document_id,
                review.document.title if review.document is not None else "",
                review.created_at,
                _bool_cell(bool(review.needs_review)),
                review.confidence,
                review.readiness,
                REASON_CODE_DELIMITER.join(review.reason_codes_json),
                _none_to_empty(review.error),
            ]
        )

    return build_csv_response("reviews-export.csv", rows)


@router.get("/{review_id}", response_model=ReviewResponse)
def get_review(review_id: UUID, db: Session = Depends(get_db)) -> ReviewResponse:
    repo = ReviewRepository(db)
    review = repo.get_by_id(str(review_id))
    if review is None:
        raise HTTPException(status_code=404, detail="Проверка не найдена")
    return ReviewResponse.from_model(review)


@router.get(
    "/{review_id}/export",
    response_class=Response,
    responses={
        200: {
            "description": "CSV-файл с одной проверкой (поле/значение)",
            "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
def export_review(review_id: UUID, db: Session = Depends(get_db)) -> Response:
    repo = ReviewRepository(db)
    review = repo.get_by_id(str(review_id))
    if review is None:
        raise HTTPException(status_code=404, detail="Проверка не найдена")

    document = DocumentRepository(db).get_by_id(review.document_id)

    rows: list[list[str]] = [
        ["Поле", "Значение"],
        ["ID проверки", review.id],
        ["ID документа", review.document_id],
        ["Название документа", document.title if document is not None else ""],
        ["Дата создания", review.created_at],
        ["Требуется ручная проверка", _bool_cell(bool(review.needs_review))],
        ["Уверенность", review.confidence],
        ["Готовность документа", review.readiness],
        ["Коды причин", REASON_CODE_DELIMITER.join(review.reason_codes_json)],
        ["Ошибка", _none_to_empty(review.error)],
        ["Полный результат JSON", serialize_json_cell(review.review_json)],
    ]

    return build_csv_response(f"review-{review.id}.csv", rows)

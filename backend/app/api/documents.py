from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_review_workflow
from app.database import get_db
from app.enums import DocumentStatus
from app.repositories.document_repository import DocumentRepository
from app.repositories.review_repository import ReviewRepository
from app.schemas.common import PaginatedResponse
from app.schemas.document import DocumentCreate, DocumentResponse
from app.schemas.review import ReviewResponse
from app.services.document_service import DocumentService
from app.services.review_workflow import DocumentNotFoundError, ReviewWorkflow

router = APIRouter()


@router.post("", response_model=DocumentResponse, status_code=201)
def create_document(payload: DocumentCreate, db: Session = Depends(get_db)) -> DocumentResponse:
    service = DocumentService(db)
    document = service.create_document(title=payload.title, text=payload.text)
    return DocumentResponse.model_validate(document)


@router.get("", response_model=PaginatedResponse[DocumentResponse])
def list_documents(
    status: Optional[DocumentStatus] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> PaginatedResponse[DocumentResponse]:
    repo = DocumentRepository(db)
    items, total = repo.list(
        status=status.value if status is not None else None,
        limit=limit,
        offset=offset,
    )
    return PaginatedResponse(
        items=[DocumentResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(document_id: UUID, db: Session = Depends(get_db)) -> DocumentResponse:
    repo = DocumentRepository(db)
    document = repo.get_by_id(str(document_id))
    if document is None:
        raise HTTPException(status_code=404, detail="Документ не найден")
    return DocumentResponse.model_validate(document)


@router.post(
    "/{document_id}/review",
    response_model=ReviewResponse,
    status_code=201,
    summary="Запустить и сохранить проверку документа",
    description=(
        "Запускает проверку уже сохранённого документа и атомарно сохраняет Review и "
        "AuditRun. Безопасный резервный результат (safe fallback) возвращается как "
        "обычный успешный ответ с needs_review=true — ручная проверка, а не ошибка."
    ),
)
def review_document(
    document_id: UUID,
    db: Session = Depends(get_db),
    workflow: ReviewWorkflow = Depends(get_review_workflow),
) -> ReviewResponse:
    try:
        result = workflow.run(document_id)
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Документ не найден")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Не удалось выполнить проверку документа.")

    review = ReviewRepository(db).get_by_id(str(result.review_id))
    return ReviewResponse.from_model(review)

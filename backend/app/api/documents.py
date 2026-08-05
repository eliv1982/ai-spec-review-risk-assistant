from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.enums import DocumentStatus
from app.repositories.document_repository import DocumentRepository
from app.schemas.common import PaginatedResponse
from app.schemas.document import DocumentCreate, DocumentResponse
from app.services.document_service import DocumentService

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

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.enums import AuditStatus
from app.repositories.audit_repository import AuditRunRepository
from app.schemas.audit import AuditRunResponse
from app.schemas.common import PaginatedResponse

router = APIRouter()


@router.get("", response_model=PaginatedResponse[AuditRunResponse])
def list_audit_runs(
    status: Optional[AuditStatus] = Query(default=None),
    action: Optional[str] = Query(default=None),
    errors_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> PaginatedResponse[AuditRunResponse]:
    if action is not None:
        action = action.strip()
        if not action:
            raise HTTPException(status_code=422, detail="Параметр action не может быть пустым")

    repo = AuditRunRepository(db)
    items, total = repo.list(
        status=status.value if status is not None else None,
        action=action,
        errors_only=errors_only,
        limit=limit,
        offset=offset,
    )
    return PaginatedResponse(
        items=[AuditRunResponse.from_model(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{audit_run_id}", response_model=AuditRunResponse)
def get_audit_run(audit_run_id: UUID, db: Session = Depends(get_db)) -> AuditRunResponse:
    repo = AuditRunRepository(db)
    audit_run = repo.get_by_id(str(audit_run_id))
    if audit_run is None:
        raise HTTPException(status_code=404, detail="Запись аудита не найдена")
    return AuditRunResponse.from_model(audit_run)

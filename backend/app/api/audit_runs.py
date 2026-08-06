from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.enums import AuditStatus
from app.repositories.audit_repository import AuditRunRepository
from app.schemas.audit import AuditRunResponse
from app.schemas.common import PaginatedResponse
from app.services.csv_export import build_csv_response, serialize_json_cell

router = APIRouter()


def _none_to_empty(value: Optional[str]) -> str:
    return value if value is not None else ""


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


# Registered before `/{audit_run_id}` for the same static-vs-dynamic-route
# reason documented in `app/api/reviews.py`.
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
            "description": "CSV-файл с записями аудита",
            "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
def export_audit_runs(
    status: Optional[AuditStatus] = Query(default=None),
    action: Optional[str] = Query(default=None),
    errors_only: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> Response:
    if action is not None:
        action = action.strip()
        if not action:
            raise HTTPException(status_code=422, detail="Параметр action не может быть пустым")

    repo = AuditRunRepository(db)
    items = repo.list_all_for_export(
        status=status.value if status is not None else None,
        action=action,
        errors_only=errors_only,
    )

    rows: list[list[str]] = [
        [
            "ID записи",
            "Действие",
            "Тип сущности",
            "ID сущности",
            "Статус",
            "Длительность, мс",
            "Ошибка",
            "Дата создания",
            "Детали JSON",
        ]
    ]
    for run in items:
        details = {"input_json": run.input_json, "output_json": run.output_json}
        rows.append(
            [
                run.id,
                run.action,
                _none_to_empty(run.entity_type),
                _none_to_empty(run.entity_id),
                run.status,
                str(run.duration_ms),
                _none_to_empty(run.error),
                run.created_at,
                serialize_json_cell(details),
            ]
        )

    return build_csv_response("audit-runs-export.csv", rows)


@router.get("/{audit_run_id}", response_model=AuditRunResponse)
def get_audit_run(audit_run_id: UUID, db: Session = Depends(get_db)) -> AuditRunResponse:
    repo = AuditRunRepository(db)
    audit_run = repo.get_by_id(str(audit_run_id))
    if audit_run is None:
        raise HTTPException(status_code=404, detail="Запись аудита не найдена")
    return AuditRunResponse.from_model(audit_run)

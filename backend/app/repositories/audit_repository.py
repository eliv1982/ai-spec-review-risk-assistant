from typing import Any, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import AuditStatus
from app.models import AuditRun


class AuditRunRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(
        self,
        *,
        action: str,
        status: str,
        duration_ms: int,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        input_json: Optional[Any] = None,
        output_json: Optional[Any] = None,
        error: Optional[str] = None,
    ) -> AuditRun:
        audit_run = AuditRun(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            input_json=input_json,
            output_json=output_json,
            status=status,
            error=error,
            duration_ms=duration_ms,
        )
        self.db.add(audit_run)
        return audit_run

    def get_by_id(self, audit_run_id: str) -> Optional[AuditRun]:
        return self.db.get(AuditRun, audit_run_id)

    def list(
        self,
        *,
        status: Optional[str] = None,
        action: Optional[str] = None,
        errors_only: bool = False,
        limit: int,
        offset: int,
    ) -> tuple[Sequence[AuditRun], int]:
        filters = []
        if status is not None:
            filters.append(AuditRun.status == status)
        if errors_only:
            filters.append(AuditRun.status == AuditStatus.error.value)
        if action is not None:
            filters.append(AuditRun.action == action)

        total = self.db.scalar(select(func.count()).select_from(AuditRun).where(*filters)) or 0

        stmt = (
            select(AuditRun)
            .where(*filters)
            .order_by(AuditRun.created_at.desc(), AuditRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
        items = self.db.scalars(stmt).all()
        return items, total

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

    def _filters(
        self,
        *,
        status: Optional[str],
        action: Optional[str],
        errors_only: bool,
    ) -> list[Any]:
        filters: list[Any] = []
        if status is not None:
            filters.append(AuditRun.status == status)
        if errors_only:
            filters.append(AuditRun.status == AuditStatus.error.value)
        if action is not None:
            filters.append(AuditRun.action == action)
        return filters

    def list(
        self,
        *,
        status: Optional[str] = None,
        action: Optional[str] = None,
        errors_only: bool = False,
        limit: int,
        offset: int,
    ) -> tuple[Sequence[AuditRun], int]:
        filters = self._filters(status=status, action=action, errors_only=errors_only)

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

    def list_all_for_export(
        self,
        *,
        status: Optional[str] = None,
        action: Optional[str] = None,
        errors_only: bool = False,
    ) -> Sequence[AuditRun]:
        """Same filters and ordering as `list`, without `limit`/`offset` — used
        only by CSV export, never by the paginated list endpoint."""
        filters = self._filters(status=status, action=action, errors_only=errors_only)

        stmt = (
            select(AuditRun)
            .where(*filters)
            .order_by(AuditRun.created_at.desc(), AuditRun.id.desc())
        )
        return self.db.scalars(stmt).all()

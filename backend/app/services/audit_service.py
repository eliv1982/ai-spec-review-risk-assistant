from typing import Any, Optional

from sqlalchemy.orm import Session

from app.enums import AuditStatus
from app.models import AuditRun
from app.repositories.audit_repository import AuditRunRepository


def validate_audit_invariant(status: str, error: Optional[str]) -> None:
    """Enforce the audit_runs status/error invariant (DATA_MODEL.md, ARCHITECTURE.md).

    status == "error"                      -> error must be a non-empty sanitized string
    status in ("success", "needs_review")  -> error must be null
    """
    if status == AuditStatus.error.value:
        if not error or not error.strip():
            raise ValueError("audit_runs.error must be a non-empty sanitized string when status='error'")
    elif error is not None:
        raise ValueError("audit_runs.error must be null when status is 'success' or 'needs_review'")


class AuditService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = AuditRunRepository(db)

    def record(
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
        validate_audit_invariant(status, error)
        if duration_ms < 0:
            raise ValueError("audit_runs.duration_ms must be >= 0")

        return self.repo.add(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            input_json=input_json,
            output_json=output_json,
            status=status,
            error=error,
            duration_ms=duration_ms,
        )

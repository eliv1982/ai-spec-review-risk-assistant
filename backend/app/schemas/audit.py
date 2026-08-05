from typing import Any, Dict, Optional

from pydantic import BaseModel

from app.enums import AuditStatus
from app.models import AuditRun as AuditRunModel


class AuditRunResponse(BaseModel):
    id: str
    created_at: str
    action: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    input_json: Optional[Dict[str, Any]] = None
    output_json: Optional[Dict[str, Any]] = None
    status: AuditStatus
    error: Optional[str] = None
    duration_ms: int

    @classmethod
    def from_model(cls, audit_run: AuditRunModel) -> "AuditRunResponse":
        return cls(
            id=audit_run.id,
            created_at=audit_run.created_at,
            action=audit_run.action,
            entity_type=audit_run.entity_type,
            entity_id=audit_run.entity_id,
            input_json=audit_run.input_json,
            output_json=audit_run.output_json,
            status=audit_run.status,
            error=audit_run.error,
            duration_ms=audit_run.duration_ms,
        )

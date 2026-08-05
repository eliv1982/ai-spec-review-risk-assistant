import time

from sqlalchemy.orm import Session

from app.enums import AuditStatus
from app.models import Document
from app.repositories.document_repository import DocumentRepository
from app.services.audit_service import AuditService


class DocumentService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.documents = DocumentRepository(db)
        self.audit = AuditService(db)

    def create_document(self, *, title: str, text: str) -> Document:
        """Atomically persist the document and its document.create audit row.

        If the audit row cannot be recorded, the whole transaction is rolled
        back so the creation is never reported as successful without an audit trail.

        The audit snapshot intentionally stores only non-secret metadata (field
        lengths, id, status) — never the raw title or document text — since
        audit_runs.input_json/output_json must never leak user-supplied content
        that may contain credentials or other sensitive values.
        """
        start = time.perf_counter()
        try:
            document = self.documents.add(title=title, text=text)
            self.db.flush()  # assigns id/created_at so the audit row can reference them

            duration_ms = max(0, round((time.perf_counter() - start) * 1000))

            self.audit.record(
                action="document.create",
                entity_type="document",
                entity_id=document.id,
                input_json={
                    "title_length": len(document.title),
                    "text_length": len(document.text),
                },
                output_json={"document_id": document.id, "status": document.status},
                status=AuditStatus.success.value,
                error=None,
                duration_ms=duration_ms,
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        self.db.refresh(document)
        return document

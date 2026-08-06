from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditRun, Document, Review
from app.repositories.audit_repository import AuditRunRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.review_repository import ReviewRepository

SAMPLE_FINAL_REVIEW: dict[str, Any] = {
    "summary": "The brief leaves data retention unspecified.",
    "risks": [],
    "missing_requirements": [],
    "contradictions": [],
    "questions_to_client": ["What is the retention period?"],
    "acceptance_criteria": [],
    "confidence": "low",
    "document_readiness": "not_ready",
    "needs_review": True,
    "review_reason_codes": ["LOW_CONFIDENCE"],
}


def make_document(db_session: Session, *, title: str = "Doc", text: str = "Some text") -> Document:
    repo = DocumentRepository(db_session)
    document = repo.add(title=title, text=text)
    db_session.commit()
    db_session.refresh(document)
    return document


def make_review(
    db_session: Session,
    *,
    document_id: str,
    review_json: Optional[dict[str, Any]] = None,
    confidence: str = "low",
    readiness: str = "not_ready",
    needs_review: bool = True,
    reason_codes: Optional[list[str]] = None,
    error: Optional[str] = None,
) -> Review:
    """Persist a review fixture whose denormalized columns always match review_json.

    In production, confidence/readiness/needs_review/review_reason_codes are all
    derived from a single FinalReview object, so they can never diverge from the
    review_json they came from. To keep fixtures equally consistent, the four
    review_json fields that mirror those columns are always forced to match the
    confidence/readiness/needs_review/reason_codes arguments actually used here,
    regardless of what a caller-supplied review_json template already contains.
    """
    codes = list(reason_codes) if reason_codes is not None else ["LOW_CONFIDENCE"]
    base_review_json = dict(review_json) if review_json is not None else dict(SAMPLE_FINAL_REVIEW)
    base_review_json["confidence"] = confidence
    base_review_json["document_readiness"] = readiness
    base_review_json["needs_review"] = needs_review
    base_review_json["review_reason_codes"] = codes

    repo = ReviewRepository(db_session)
    review = repo.add(
        document_id=document_id,
        review_json=base_review_json,
        confidence=confidence,
        readiness=readiness,
        needs_review=needs_review,
        reason_codes=codes,
        error=error,
    )
    db_session.commit()
    db_session.refresh(review)
    return review


def make_audit_run(
    db_session: Session,
    *,
    action: str = "document.create",
    status: str = "success",
    duration_ms: int = 5,
    entity_type: Optional[str] = "document",
    entity_id: Optional[str] = None,
    input_json: Optional[dict[str, Any]] = None,
    output_json: Optional[dict[str, Any]] = None,
    error: Optional[str] = None,
) -> AuditRun:
    repo = AuditRunRepository(db_session)
    audit_run = repo.add(
        action=action,
        status=status,
        duration_ms=duration_ms,
        entity_type=entity_type,
        entity_id=entity_id,
        input_json=input_json,
        output_json=output_json,
        error=error,
    )
    db_session.commit()
    db_session.refresh(audit_run)
    return audit_run


def audit_run_snapshot(db_session: Session) -> tuple[tuple[Any, ...], ...]:
    """Deterministic, immutable snapshot of every `audit_runs` row's actual
    persisted state — every column on the `AuditRun` model, not just row
    count or ids.

    Used by "this operation must not write to audit_runs" regression tests:
    comparing two snapshots for exact equality catches an added row, a
    removed row, *and* an in-place mutation of an existing row's
    action/status/error/input_json/output_json/etc — a plain `len(...)` or
    id-set comparison would miss that last case entirely (e.g. a row silently
    rewritten from `status="success"` to `status="error"` without any row
    being added or removed).

    `expire_all()` runs first because the caller's `db_session` and the
    session the FastAPI app itself uses per-request (`get_db`) are different
    `Session` objects bound to the same engine — without expiring, a row
    already loaded into `db_session`'s identity map by an earlier snapshot
    call would keep serving its stale in-memory attribute values instead of
    re-querying the database for whatever the app's own session most
    recently committed.
    """
    db_session.expire_all()
    stmt = select(AuditRun).order_by(AuditRun.created_at, AuditRun.id)
    rows = db_session.scalars(stmt).all()
    return tuple(
        (
            row.id,
            row.created_at,
            row.action,
            row.entity_type,
            row.entity_id,
            row.input_json,
            row.output_json,
            row.status,
            row.error,
            row.duration_ms,
        )
        for row in rows
    )

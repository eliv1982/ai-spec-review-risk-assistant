"""Review persistence and audit workflow (application/service layer, not an API endpoint).

Wires an injected orchestrator (`app.services.review_orchestrator.ReviewOrchestrator`,
or any test double structurally satisfying `ReviewOrchestratorProtocol`) to the
existing `documents` / `reviews` / `audit_runs` persistence for an already-stored
document:

    existing Document -> orchestrator.review(document.text) -> ReviewOrchestrationResult
    -> atomic (Review insert + audit_runs insert) -> PersistedReviewResult

The orchestrator is called at most once and is never constructed here: this module
never imports `OpenAIReviewClient`, never talks to OpenAI, and never re-implements
QC, the fallback factory, or the prompt. `LLMClientError` is already handled inside
the orchestrator (safe fallback `FinalReview`); it can never reach this module.

Transaction boundary: the injected `Session` is never left holding an open
transaction across the (potentially slow, external) orchestrator call. After the
first document load, its id/text are copied into plain local values and the
read-only autobegun transaction is closed (`session.rollback()`) *before* calling
`orchestrator.review(...)`. A short write transaction is opened only afterwards, to
re-check the document still exists and persist `Review` + `AuditRun` together. All
values needed by the returned result are read while objects are still attached and
unexpired (right after `flush()`, before `commit()`), so no post-commit ORM refresh
is ever needed and the session is left with no open transaction on every return path.

Audit status for a persisted review is derived only from the final `FinalReview`:

    final_review.needs_review is False -> AuditStatus.success
    final_review.needs_review is True  -> AuditStatus.needs_review

A safe LLM fallback (`used_fallback=True`) that produced a usable `FinalReview` is
therefore audited as `needs_review` with `error=None` — it is a successfully
persisted, safe result, not a technical audit failure. `used_fallback` and
`llm_error_category` are recorded as orchestration metadata inside the audit
`input_json`/`output_json`, never as `audit_runs.error` and never folded into
`FinalReview.review_reason_codes`. Before any database write, the orchestration
result is checked for internal consistency (`used_fallback=True` must imply
`final_review.needs_review=True`) — the stock `ReviewOrchestrator` never violates
this, but nothing stops a non-conforming injected implementation from doing so, and
this workflow refuses to persist a contradictory row rather than silently trusting it.

Only a genuinely unexpected failure (a bug in the orchestrator/QC/persistence code,
an invalid orchestration result, never a typed `LLMClientError`) is audited as
`status="error"`: the failed transaction is rolled back, no `Review` row is left
behind, and a separate audit-only transaction records a fixed, non-secret error
summary (never `str(exc)`, a traceback, the document text, or a provider payload)
referencing the document before the original exception is re-raised unchanged. If
that secondary audit write itself fails, it is swallowed so it never masks the
original error. `BaseException` subclasses that are not `Exception` (in particular
`KeyboardInterrupt`, `SystemExit`, `GeneratorExit`) are never caught here at all.

Out of scope here: HTTP endpoints, HTTP status mapping, JSON export, retries, a
second LLM call, background tasks/queues, review-version comparison, and any
change to `Document.status` — see backend/README.md.
"""

import time
from typing import Optional, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StrictBool, model_validator
from sqlalchemy.orm import Session

from app.enums import AuditStatus, LLMErrorCategory
from app.llm.prompts import PROMPT_VERSION, REVIEW_SCHEMA_VERSION
from app.models import Document
from app.repositories.document_repository import DocumentRepository
from app.repositories.review_repository import ReviewRepository
from app.schemas.review import FinalReview
from app.services.audit_service import AuditService
from app.services.review_orchestrator import ReviewOrchestrationResult

_AUDIT_ACTION = "document.review"

_UNEXPECTED_ERROR_AUDIT_MESSAGE = (
    "Не удалось выполнить workflow проверки документа из-за непредвиденной ошибки приложения."
)


class DocumentNotFoundError(Exception):
    """Raised when `ReviewWorkflow.run()` is given a document id with no matching row.

    Raised both when the document is missing on the initial load and when it has
    disappeared by the time the write transaction re-checks it. Either way: no
    `Review` row, no success/needs_review audit row, no orchestrator call (for the
    initial-load case), and — since this is "no document to review", not "a review
    attempt failed" — no error audit row either; the architecture only documents an
    audit row once a review was actually attempted against an existing document.
    """

    def __init__(self, document_id: str) -> None:
        super().__init__(f"Document {document_id} not found")
        self.document_id = document_id


class InvalidReviewWorkflowResultError(Exception):
    """Raised when an injected orchestrator returns an internally inconsistent result.

    The stock `ReviewOrchestrator` never produces `used_fallback=True` together with
    `final_review.needs_review=False` — `build_fallback_review()` always sets
    `needs_review=True` — but `ReviewOrchestrationResult` itself only validates
    `used_fallback`/`llm_error_category` consistency, not the resulting
    `final_review.needs_review`. Persisting that combination would silently store a
    safe-fallback outcome as a confident `success` review, so it is rejected before
    any `Review`/`AuditRun` row is created.
    """


class ReviewOrchestratorProtocol(Protocol):
    """Minimal surface the workflow needs from a review orchestrator.

    Structurally satisfied by `app.services.review_orchestrator.ReviewOrchestrator`
    and by any offline test double; the workflow never constructs an orchestrator
    or an LLM client itself.
    """

    def review(self, document_text: str) -> ReviewOrchestrationResult: ...


class PersistedFinalReviewSnapshot(FinalReview):
    """Immutable snapshot of a `FinalReview`, safe to embed in a frozen result.

    `FinalReview` (`app/schemas/review.py`) is a plain, mutable Pydantic model shared
    with QC, the fallback factory, and `ModelReviewDraft`'s sibling schema; changing
    its config to `frozen=True` there would affect all of those. A `frozen=True`
    outer `PersistedReviewResult` alone does not stop
    `result.final_review.needs_review = ...` from silently diverging from what was
    already persisted, since the nested `FinalReview` instance stays mutable. This
    workflow-local subclass only changes the config (`frozen=True`, `extra="forbid"`)
    and is built via a full `model_validate(model_dump(mode="python"))` round-trip of
    an already-validated `FinalReview`, so it stays a true `FinalReview` (via
    inheritance) without touching the shared schema or duplicating any QC rule.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


def _snapshot_final_review(final_review: FinalReview) -> PersistedFinalReviewSnapshot:
    return PersistedFinalReviewSnapshot.model_validate(final_review.model_dump(mode="python"))


def _validate_orchestration_result(result: ReviewOrchestrationResult) -> None:
    """Reject an internally inconsistent orchestration result before any DB write.

    `ReviewOrchestrationResult` already guarantees `used_fallback` and
    `llm_error_category` agree with each other; the one gap it leaves open is
    `used_fallback=True` paired with a `final_review.needs_review=False` — a
    combination the stock orchestrator never produces but that a non-conforming
    injected implementation is not otherwise prevented from returning.
    """
    if result.used_fallback and not result.final_review.needs_review:
        raise InvalidReviewWorkflowResultError(
            "orchestration result is invalid: used_fallback=True requires "
            "final_review.needs_review=True"
        )


class PersistedReviewResult(BaseModel):
    """Typed outcome of a persisted document review, handed to a future API layer.

    Frozen and closed: a later layer can read but never mutate what was actually
    persisted. Carries only safe, already-validated, detached data — no ORM
    `Session`, no ORM instance, no exception, and no provider object. `final_review`
    is always a `PersistedFinalReviewSnapshot`, so it cannot be mutated in place
    either.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    review_id: UUID
    document_id: UUID
    final_review: FinalReview
    audit_run_id: UUID
    audit_status: AuditStatus
    used_fallback: StrictBool
    llm_error_category: Optional[LLMErrorCategory] = None

    @model_validator(mode="after")
    def _check_invariants(self) -> "PersistedReviewResult":
        if self.audit_status not in (AuditStatus.success, AuditStatus.needs_review):
            raise ValueError(
                "PersistedReviewResult.audit_status must be 'success' or 'needs_review'"
            )
        if self.used_fallback and self.llm_error_category is None:
            raise ValueError("llm_error_category is required when used_fallback is True")
        if not self.used_fallback and self.llm_error_category is not None:
            raise ValueError("llm_error_category must be None when used_fallback is False")
        if self.audit_status == AuditStatus.success and self.final_review.needs_review:
            raise ValueError("audit_status='success' requires final_review.needs_review is False")
        if self.audit_status == AuditStatus.needs_review and not self.final_review.needs_review:
            raise ValueError("audit_status='needs_review' requires final_review.needs_review is True")
        if self.used_fallback and self.audit_status != AuditStatus.needs_review:
            raise ValueError("used_fallback=True requires audit_status='needs_review'")
        if self.audit_status == AuditStatus.success and self.used_fallback:
            raise ValueError("audit_status='success' forbids used_fallback=True")
        return self


def _elapsed_ms(start: float) -> int:
    return max(0, round((time.perf_counter() - start) * 1000))


class ReviewWorkflow:
    """Application-layer service: load a document, run orchestration once, persist.

    Not responsible for HTTP, `Document.status` transitions, retries, or building
    the orchestrator/LLM client — all of those are injected or out of scope. Never
    closes the injected `session` and never opens a second one.
    """

    def __init__(self, *, session: Session, orchestrator: ReviewOrchestratorProtocol) -> None:
        self._session = session
        self._orchestrator = orchestrator

    def run(self, document_id: UUID) -> PersistedReviewResult:
        start = time.perf_counter()
        document_id_str = str(document_id)

        document = DocumentRepository(self._session).get_by_id(document_id_str)
        if document is None:
            self._session.rollback()  # close the read-only autobegin before raising
            raise DocumentNotFoundError(document_id_str)

        document_text = document.text
        self._session.rollback()  # close the read-only autobegin before the external call

        try:
            orchestration_result = self._orchestrator.review(document_text)
            _validate_orchestration_result(orchestration_result)
        except Exception:
            self._write_error_audit(document_id_str, start)
            raise

        final_review = _snapshot_final_review(orchestration_result.final_review)
        audit_status = (
            AuditStatus.success if not final_review.needs_review else AuditStatus.needs_review
        )

        try:
            # Re-check under the write transaction: nothing guarantees the document
            # wasn't deleted while the (read-transaction-free) orchestrator call ran.
            document = self._session.get(Document, document_id_str, populate_existing=True)
            if document is None:
                raise DocumentNotFoundError(document_id_str)

            reviews = ReviewRepository(self._session)
            review = reviews.add(
                document_id=document.id,
                review_json=final_review.model_dump(mode="json"),
                confidence=final_review.confidence.value,
                readiness=final_review.document_readiness.value,
                needs_review=final_review.needs_review,
                reason_codes=[code.value for code in final_review.review_reason_codes],
                error=None,
            )
            self._session.flush()  # assigns review.id, needed below and for the audit row

            audit_run = AuditService(self._session).record(
                action=_AUDIT_ACTION,
                entity_type="review",
                entity_id=review.id,
                input_json={
                    "document_id": document.id,
                    "prompt_version": PROMPT_VERSION,
                    "review_schema_version": REVIEW_SCHEMA_VERSION,
                },
                output_json={
                    "review_id": review.id,
                    "used_fallback": orchestration_result.used_fallback,
                    "llm_error_category": (
                        orchestration_result.llm_error_category.value
                        if orchestration_result.llm_error_category is not None
                        else None
                    ),
                },
                status=audit_status.value,
                error=None,
                duration_ms=_elapsed_ms(start),
            )
            self._session.flush()  # assigns audit_run.id

            # Build and validate the detached result while review/audit_run are still
            # attached and unexpired, and *before* commit: if this raises, the
            # transaction below is never committed, and the except clause rolls the
            # partially-flushed Review/AuditRun back before writing the error audit.
            result = PersistedReviewResult(
                review_id=UUID(review.id),
                document_id=UUID(document.id),
                final_review=final_review,
                audit_run_id=UUID(audit_run.id),
                audit_status=audit_status,
                used_fallback=orchestration_result.used_fallback,
                llm_error_category=orchestration_result.llm_error_category,
            )

            self._session.commit()
        except DocumentNotFoundError:
            self._session.rollback()
            raise
        except Exception:
            self._write_error_audit(document_id_str, start)
            raise

        return result

    def _write_error_audit(self, document_id_str: str, start: float) -> None:
        """Best-effort error audit for an unexpected workflow failure.

        Rolls back any incomplete main transaction first, then records a separate
        `status="error"` audit row on the document entity with a fixed, non-secret
        message. Never re-raises: if this secondary write itself fails, it must not
        replace or hide the original exception the caller is about to re-raise.
        """
        self._session.rollback()
        try:
            AuditService(self._session).record(
                action=_AUDIT_ACTION,
                entity_type="document",
                entity_id=document_id_str,
                input_json={
                    "document_id": document_id_str,
                    "prompt_version": PROMPT_VERSION,
                    "review_schema_version": REVIEW_SCHEMA_VERSION,
                },
                output_json=None,
                status=AuditStatus.error.value,
                error=_UNEXPECTED_ERROR_AUDIT_MESSAGE,
                duration_ms=_elapsed_ms(start),
            )
            self._session.commit()
        except Exception:
            self._session.rollback()

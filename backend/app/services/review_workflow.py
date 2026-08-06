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

Recovery boundary: everything from the `orchestrator.review(...)` call through the
final `session.commit()` of the main transaction runs inside a *single* `try` in
`ReviewWorkflow.run()`, not just the orchestrator call itself. That single `try` also
covers validating the orchestration result, snapshotting `final_review`, deriving
`audit_status`/`document_status`/the outcome error message, persisting
`Review`/`AuditRun`, and building `PersistedReviewResult` — all performed by
`_prepare_persistence_outcome(...)` and the persistence code that follows it, called
from inside that `try`, never before it. A `ReviewOrchestrationResult` is never
trusted just because it is annotated with that type: a non-conforming injected
orchestrator can hand back one built via `model_construct(...)`, which bypasses all
Pydantic field validation (`used_fallback` not actually a `bool`, `llm_error_category`
missing or of an unexpected type/value, `final_review` not a real `FinalReview`).
`_validate_orchestration_result` checks these explicitly — in particular,
`llm_error_category` is never read via `.value` before its type is confirmed to be a
real `LLMErrorCategory` member — and any violation, any downstream `final_review`
re-validation (snapshot) failure, and any main-transaction persistence failure
(including the main `commit()` itself) are all handled by the exact same recovery
path described below; there is no second, differently-behaved failure path. Only a
well-typed `ReviewOrchestrationResult` carrying a genuinely valid `FinalReview` and
(when `used_fallback=True`) a real `LLMErrorCategory` member is ever treated as a
persistable technical fallback; anything else is "no usable review" (see below),
never a persisted fallback built from unverified data.

Outcome, audit status, and `Document.status` are derived from `used_fallback` first,
and only then from `final_review.needs_review` (API_CONTRACTS.md, "Persistence and
status outcomes"; DATA_MODEL.md, "DocumentStatus"/"AuditStatus"):

    used_fallback is True                                -> AuditStatus.error,        Document.status = review_failed
    used_fallback is False, final_review.needs_review     -> AuditStatus.needs_review, Document.status = reviewed
    used_fallback is False, not final_review.needs_review -> AuditStatus.success,      Document.status = reviewed

A safe LLM fallback (`used_fallback=True`) is a *technical* failure that was safely
contained, not a successful automated review: it is audited as `status="error"` with
a non-empty, sanitized `audit_runs.error` (naming only the closed `LLMErrorCategory`
value, never the original exception/message/traceback/provider payload), the
persisted `Review.error` carries the same sanitized message, and `Document.status`
becomes `review_failed` — signalling that the automated pipeline itself did not
complete, distinct from `reviewed` (a completed automated review, regardless of
whether its *content* also sets `needs_review=True`). `used_fallback` and
`llm_error_category` are additionally recorded as orchestration metadata inside the
audit `input_json`/`output_json`, and never folded into `FinalReview.review_reason_codes`.

Only a genuinely unexpected failure (a bug in the orchestrator/QC/persistence code,
an invalid or malformed orchestration result, never a typed `LLMClientError`) is
audited as `status="error"` with **no** `Review` row at all: the failed transaction is
rolled back, and a separate audit-only recovery transaction sets `Document.status =
review_failed` (best-effort: skipped if the document itself no longer exists) and
records a fixed, non-secret error summary (never `str(exc)`, a traceback, the
document text, a provider payload, or a raw/unexpected `llm_error_category` value)
referencing the document, before the original exception is re-raised unchanged. If
that secondary recovery write itself fails — including its own final `commit()` — it
is swallowed so it never masks the original error. `BaseException` subclasses that
are not `Exception` (in particular `KeyboardInterrupt`, `SystemExit`, `GeneratorExit`)
are never caught here at all.

Out of scope here: HTTP endpoints, HTTP status mapping, CSV export, retries, a
second LLM call, background tasks/queues, and review-version comparison — see
backend/README.md.
"""

import time
from typing import NamedTuple, Optional, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StrictBool, model_validator
from sqlalchemy.orm import Session

from app.enums import AuditStatus, DocumentStatus, LLMErrorCategory
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

_FALLBACK_ERROR_MESSAGE_TEMPLATE = (
    "Проверка документа вернула безопасный резервный результат "
    "(категория ошибки LLM: {category})."
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
    """Raised when an injected orchestrator returns a malformed or internally
    inconsistent result.

    Covers both structural violations that bypass Pydantic validation entirely
    (`used_fallback` not really a `bool`, `llm_error_category` missing or not a real
    `LLMErrorCategory` member when `used_fallback=True`, a stray `llm_error_category`
    when `used_fallback=False`, or `final_review` not a real `FinalReview`) and the
    one inconsistency a well-typed `ReviewOrchestrationResult` can still carry:
    `used_fallback=True` together with `final_review.needs_review=False` — the stock
    `build_fallback_review()` never produces that combination, but nothing stops a
    non-conforming injected implementation from doing so. Persisting any of these
    would either crash on unchecked attribute/`.value` access or silently store an
    unverified/contradictory row, so all of them are rejected before any
    `Review`/`AuditRun` row is created, and are handled by the exact same "no usable
    review" recovery path as any other unexpected failure (module docstring).
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
    inheritance) without touching the shared schema or duplicating any QC rule. That
    round-trip also doubles as a structural re-validation: a `final_review` that only
    *looks* like a `FinalReview` (for example, one built via `model_construct(...)`
    with missing or malformed fields) fails here with a `ValidationError`, which is
    handled by the same recovery boundary as any other unexpected failure (module
    docstring) rather than being persisted.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


def _snapshot_final_review(final_review: FinalReview) -> PersistedFinalReviewSnapshot:
    return PersistedFinalReviewSnapshot.model_validate(final_review.model_dump(mode="python"))


def _validate_orchestration_result(result: ReviewOrchestrationResult) -> None:
    """Reject a malformed or internally inconsistent orchestration result before any
    DB write or attribute access that could raise something less safe.

    Never trusts `result` just because it is annotated as a `ReviewOrchestrationResult`:
    a non-conforming injected orchestrator can construct one via `model_construct(...)`,
    bypassing Pydantic validation entirely, so every field this workflow relies on is
    checked explicitly here — in particular, `llm_error_category` is never read via
    `.value` before `isinstance(..., LLMErrorCategory)` has already confirmed its type,
    so a missing category and an unexpected category type/value are both rejected the
    same way, before either could raise an uncontrolled `AttributeError` or leak a raw
    unexpected value into a persisted message. Any violation raises
    `InvalidReviewWorkflowResultError` and is treated as "no usable review" (scenario D)
    by the caller: no persisted fallback is ever built from an unverified value.
    """
    if not isinstance(result.used_fallback, bool):
        raise InvalidReviewWorkflowResultError(
            "orchestration result is invalid: used_fallback must be a bool"
        )
    if not isinstance(result.final_review, FinalReview):
        raise InvalidReviewWorkflowResultError(
            "orchestration result is invalid: final_review must be a FinalReview"
        )

    if result.used_fallback:
        if not isinstance(result.llm_error_category, LLMErrorCategory):
            raise InvalidReviewWorkflowResultError(
                "orchestration result is invalid: used_fallback=True requires a "
                "valid llm_error_category"
            )
        if not result.final_review.needs_review:
            raise InvalidReviewWorkflowResultError(
                "orchestration result is invalid: used_fallback=True requires "
                "final_review.needs_review=True"
            )
    elif result.llm_error_category is not None:
        raise InvalidReviewWorkflowResultError(
            "orchestration result is invalid: llm_error_category must be None "
            "when used_fallback is False"
        )


class _PersistenceOutcome(NamedTuple):
    """Derived shape needed to persist an orchestration result.

    Computed exactly once, inside the recovery boundary (module docstring), so
    `ReviewWorkflow.run()` never has two independent places deciding
    `audit_status`/`document_status`/the outcome error message with different
    failure semantics.
    """

    final_review: PersistedFinalReviewSnapshot
    audit_status: AuditStatus
    document_status: DocumentStatus
    outcome_error: Optional[str]


def _prepare_persistence_outcome(orchestration_result: ReviewOrchestrationResult) -> _PersistenceOutcome:
    """Validate `orchestration_result` and derive its persistence outcome.

    Must only be called from inside `ReviewWorkflow.run()`'s single recovery-protected
    `try` (module docstring): a validation failure, a `final_review` that fails
    re-validation on snapshot, or any other unexpected error raised from here is
    handled by the exact same generic recovery path as a main-transaction persistence
    failure — never a separate, differently-behaved one.
    """
    _validate_orchestration_result(orchestration_result)
    final_review = _snapshot_final_review(orchestration_result.final_review)

    if orchestration_result.used_fallback:
        # Technical failure, safely contained: audited as `error`, not as a
        # successful/needs-review outcome (API_CONTRACTS.md, "Persistence and
        # status outcomes"). `llm_error_category` is safe to read via `.value`
        # here: `_validate_orchestration_result` already confirmed it is a real
        # `LLMErrorCategory` member.
        return _PersistenceOutcome(
            final_review=final_review,
            audit_status=AuditStatus.error,
            document_status=DocumentStatus.review_failed,
            outcome_error=_FALLBACK_ERROR_MESSAGE_TEMPLATE.format(
                category=orchestration_result.llm_error_category.value
            ),
        )
    if final_review.needs_review:
        return _PersistenceOutcome(
            final_review=final_review,
            audit_status=AuditStatus.needs_review,
            document_status=DocumentStatus.reviewed,
            outcome_error=None,
        )
    return _PersistenceOutcome(
        final_review=final_review,
        audit_status=AuditStatus.success,
        document_status=DocumentStatus.reviewed,
        outcome_error=None,
    )


class PersistedReviewResult(BaseModel):
    """Typed outcome of a persisted document review, handed to a future API layer.

    Frozen and closed: a later layer can read but never mutate what was actually
    persisted. Carries only safe, already-validated, detached data — no ORM
    `Session`, no ORM instance, no exception, and no provider object. `final_review`
    is always a `PersistedFinalReviewSnapshot`, so it cannot be mutated in place
    either. `review_error` mirrors the persisted `Review.error` column (never the
    raw exception, a traceback, or a provider payload), so a caller never has to
    infer the technical-failure signal from `needs_review`, `confidence`, or reason
    codes alone (API_CONTRACTS.md, "Persistence and status outcomes").
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    review_id: UUID
    document_id: UUID
    final_review: FinalReview
    audit_run_id: UUID
    audit_status: AuditStatus
    used_fallback: StrictBool
    llm_error_category: Optional[LLMErrorCategory] = None
    review_error: Optional[str] = None

    @model_validator(mode="after")
    def _check_invariants(self) -> "PersistedReviewResult":
        if self.used_fallback and self.llm_error_category is None:
            raise ValueError("llm_error_category is required when used_fallback is True")
        if not self.used_fallback and self.llm_error_category is not None:
            raise ValueError("llm_error_category must be None when used_fallback is False")

        if self.used_fallback:
            # A persisted safe fallback is always audited as a technical failure
            # (API_CONTRACTS.md, "Persistence and status outcomes"): never
            # `success`/`needs_review`, and always a non-empty sanitized
            # `review_error` mirroring `Review.error`/`audit_runs.error`.
            if self.audit_status != AuditStatus.error:
                raise ValueError("used_fallback=True requires audit_status='error'")
            if not self.final_review.needs_review:
                raise ValueError("used_fallback=True requires final_review.needs_review=True")
            if not self.review_error or not self.review_error.strip():
                raise ValueError(
                    "review_error must be a non-empty sanitized string when used_fallback is True"
                )
        else:
            if self.audit_status == AuditStatus.error:
                raise ValueError("audit_status='error' requires used_fallback=True")
            if self.review_error is not None:
                raise ValueError("review_error must be None when used_fallback is False")
            if self.audit_status == AuditStatus.success and self.final_review.needs_review:
                raise ValueError("audit_status='success' requires final_review.needs_review is False")
            if self.audit_status == AuditStatus.needs_review and not self.final_review.needs_review:
                raise ValueError(
                    "audit_status='needs_review' requires final_review.needs_review is True"
                )
        return self


def _elapsed_ms(start: float) -> int:
    return max(0, round((time.perf_counter() - start) * 1000))


class ReviewWorkflow:
    """Application-layer service: load a document, run orchestration once, persist.

    Not responsible for HTTP, retries, or building the orchestrator/LLM client —
    all of those are injected or out of scope. `Document.status` transitions
    (`reviewed` / `review_failed`) *are* this workflow's responsibility, decided
    together with the audit outcome (see module docstring). Never closes the
    injected `session` and never opens a second one.
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
            # Everything from here through the main `commit()` below is inside one
            # recovery-protected `try` (module docstring, "Recovery boundary"):
            # orchestration-result validation, `final_review` snapshotting, deriving
            # audit/document status, persistence, and building the returned result.
            orchestration_result = self._orchestrator.review(document_text)
            outcome = _prepare_persistence_outcome(orchestration_result)

            # Re-check under the write transaction: nothing guarantees the document
            # wasn't deleted while the (read-transaction-free) orchestrator call ran.
            document = self._session.get(Document, document_id_str, populate_existing=True)
            if document is None:
                raise DocumentNotFoundError(document_id_str)

            document.status = outcome.document_status.value

            reviews = ReviewRepository(self._session)
            review = reviews.add(
                document_id=document.id,
                review_json=outcome.final_review.model_dump(mode="json"),
                confidence=outcome.final_review.confidence.value,
                readiness=outcome.final_review.document_readiness.value,
                needs_review=outcome.final_review.needs_review,
                reason_codes=[code.value for code in outcome.final_review.review_reason_codes],
                error=outcome.outcome_error,
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
                status=outcome.audit_status.value,
                error=outcome.outcome_error,
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
                final_review=outcome.final_review,
                audit_run_id=UUID(audit_run.id),
                audit_status=outcome.audit_status,
                used_fallback=orchestration_result.used_fallback,
                llm_error_category=orchestration_result.llm_error_category,
                review_error=outcome.outcome_error,
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

        Rolls back any incomplete main transaction first, then — in one recovery
        transaction — sets `Document.status = review_failed` (skipped if the
        document no longer exists; never raises on its own) and records a separate
        `status="error"` audit row on the document entity with a fixed, non-secret
        message. Never re-raises: if this secondary write itself fails (including its
        own final `commit()`), it must not replace or hide the original exception the
        caller is about to re-raise, and the attempted `Document.status` change is
        rolled back along with it so no partially-consistent state is ever left
        behind.
        """
        self._session.rollback()
        try:
            document = self._session.get(Document, document_id_str)
            if document is not None:
                document.status = DocumentStatus.review_failed.value

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

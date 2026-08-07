"""Offline unit/integration tests for the review persistence and audit workflow
(backend/app/services/review_workflow.py).

No test here touches the network, the real OpenAI SDK, or `OPENAI_API_KEY`: the
orchestrator is always an injected fake satisfying `ReviewOrchestratorProtocol`,
and persistence runs against the isolated temp SQLite database wired up in
tests/conftest.py.
"""

import uuid
from typing import List, Optional
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.enums import AuditStatus, DocumentStatus, LLMErrorCategory, ReviewReasonCode
from app.llm.prompts import PROMPT_VERSION, REVIEW_SCHEMA_VERSION
from app.models import AuditRun, Document, Review
from app.repositories.audit_repository import AuditRunRepository
from app.repositories.review_repository import ReviewRepository
from app.schemas.review import Contradiction, FinalReview, MissingRequirement, Risk
from app.services.audit_service import AuditService
from app.services.review_orchestrator import ReviewOrchestrationResult
from app.services.review_qc import build_fallback_review
import app.services.review_workflow as workflow_module
from app.services.review_workflow import (
    DocumentNotFoundError,
    InvalidReviewWorkflowResultError,
    PersistedFinalReviewSnapshot,
    PersistedReviewResult,
    ReviewWorkflow,
)
from tests.helpers import make_document

NON_VAGUE_TEXT = (
    "The system shall allow an authenticated administrator to configure "
    "notification delivery preferences, including channel selection, retry "
    "policy, and retention period, and every configuration change must be "
    "recorded in an audit log entry that is visible to operators within the "
    "administration panel for later review and compliance reporting purposes."
)

DANGEROUS_ERROR_TEXT = (
    'sk-test-secret leaked; Authorization: Bearer secret used; '
    'raw-provider-body {"secret": "leak"} returned'
)

FALLBACK_CATEGORY_ROOT_CODES = [
    pytest.param(LLMErrorCategory.CONFIGURATION_ERROR, ReviewReasonCode.MODEL_ERROR, id="configuration"),
    pytest.param(LLMErrorCategory.TRANSPORT_ERROR, ReviewReasonCode.MODEL_ERROR, id="transport"),
    pytest.param(LLMErrorCategory.API_ERROR, ReviewReasonCode.MODEL_ERROR, id="api"),
    pytest.param(LLMErrorCategory.INVALID_JSON, ReviewReasonCode.INVALID_JSON, id="invalid_json"),
    pytest.param(LLMErrorCategory.SCHEMA_MISMATCH, ReviewReasonCode.SCHEMA_MISMATCH, id="schema_mismatch"),
    pytest.param(LLMErrorCategory.PROVIDER_ERROR, ReviewReasonCode.MODEL_ERROR, id="provider"),
]


class _FakeOrchestrator:
    """Injected fake satisfying `ReviewOrchestratorProtocol`; never touches an LLM.

    When constructed with `track_session`, each `review()` call records that
    session's `in_transaction()` state at call time, so tests can prove the
    workflow closed its read transaction before calling the orchestrator.
    """

    def __init__(
        self,
        *,
        result: Optional[ReviewOrchestrationResult] = None,
        exception: Optional[BaseException] = None,
        track_session=None,
    ) -> None:
        self._result = result
        self._exception = exception
        self._track_session = track_session
        self.calls: List[str] = []
        self.in_transaction_snapshots: List[bool] = []

    def review(self, document_text: str) -> ReviewOrchestrationResult:
        self.calls.append(document_text)
        if self._track_session is not None:
            self.in_transaction_snapshots.append(self._track_session.in_transaction())
        if self._exception is not None:
            raise self._exception
        assert self._result is not None
        return self._result


class _DocumentDeletingOrchestrator:
    """Simulates a document being deleted by a concurrent operation mid-review.

    Deletes and commits the document row (using the same session, the only way to
    reliably simulate a concurrent deletion against a single-connection SQLite test
    database) from inside `review()`, i.e. between the workflow's initial read and
    its write-phase re-check.
    """

    def __init__(self, *, session, document_id: str, result: ReviewOrchestrationResult) -> None:
        self._session = session
        self._document_id = document_id
        self._result = result
        self.calls: List[str] = []

    def review(self, document_text: str) -> ReviewOrchestrationResult:
        self.calls.append(document_text)
        document = self._session.get(Document, self._document_id)
        self._session.delete(document)
        self._session.commit()
        return self._result


def _final_review(*, needs_review: bool, reason_codes: list, **overrides) -> FinalReview:
    base = dict(
        summary="Summary of the reviewed specification.",
        risks=[],
        missing_requirements=[],
        contradictions=[],
        questions_to_client=["Question one?", "Question two?", "Question three?"],
        acceptance_criteria=["Given X, when Y, then Z."],
        confidence="high",
        document_readiness="ready",
        needs_review=needs_review,
        review_reason_codes=reason_codes,
    )
    base.update(overrides)
    return FinalReview(**base)


def _orchestration_result(
    final_review: FinalReview, *, used_fallback: bool, llm_error_category=None
) -> ReviewOrchestrationResult:
    return ReviewOrchestrationResult(
        final_review=final_review,
        used_fallback=used_fallback,
        llm_error_category=llm_error_category,
    )


def _rich_final_review() -> FinalReview:
    return FinalReview(
        summary="Комплексное summary с несколькими находками.",
        risks=[
            Risk(
                severity="high",
                category="security",
                description="Нет аутентификации для административного API.",
                evidence="Административный API доступен без проверки личности.",
            ),
            Risk(
                severity="low",
                category="other",
                description="Неясен формат логирования.",
                evidence=None,
            ),
        ],
        missing_requirements=[
            MissingRequirement(category="data", description="Не указан срок хранения данных."),
        ],
        contradictions=[
            Contradiction(
                description="Документ одновременно требует и запрещает автосохранение.",
                evidence=["Автосохранение включено по умолчанию.", "Автосохранение запрещено политикой."],
            ),
        ],
        questions_to_client=["Каков срок хранения данных?", "Нужна ли многофакторная аутентификация?"],
        acceptance_criteria=["Given X, when Y, then Z.", "Given A, when B, then C."],
        confidence="medium",
        document_readiness="needs_clarification",
        needs_review=True,
        review_reason_codes=[ReviewReasonCode.LOW_CONFIDENCE, ReviewReasonCode.CONTRADICTORY_INPUT],
    )


# ---------------------------------------------------------------------------
# A. Happy path
# ---------------------------------------------------------------------------


def test_happy_path_persists_review_and_audit(db_session):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    final_review = _final_review(needs_review=False, reason_codes=[])
    fake = _FakeOrchestrator(result=_orchestration_result(final_review, used_fallback=False))
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    result = workflow.run(UUID(document.id))

    assert isinstance(result, PersistedReviewResult)
    assert fake.calls == [document.text]

    stored_review = db_session.get(Review, str(result.review_id))
    assert stored_review is not None
    assert stored_review.document_id == document.id
    assert stored_review.needs_review == 0
    assert stored_review.reason_codes_json == []
    assert stored_review.error is None

    stored_audit = db_session.get(AuditRun, str(result.audit_run_id))
    assert stored_audit is not None
    assert stored_audit.action == "document.review"
    assert stored_audit.entity_type == "review"
    assert stored_audit.entity_id == stored_review.id
    assert stored_audit.status == "success"
    assert stored_audit.error is None
    assert stored_audit.duration_ms >= 0
    assert stored_audit.input_json["prompt_version"] == "spec-review-prompt-v2"
    assert stored_audit.input_json["review_schema_version"] == "spec-review-schema-v1"
    assert stored_audit.output_json["used_fallback"] is False
    assert stored_audit.output_json["llm_error_category"] is None

    assert result.document_id == UUID(document.id)
    # `result.final_review` is a `PersistedFinalReviewSnapshot`, a distinct class from
    # `FinalReview` by design (see section J below), so compare field values instead
    # of relying on Pydantic's class-sensitive `==`.
    assert result.final_review.model_dump(mode="python") == final_review.model_dump(mode="python")
    assert result.audit_status == AuditStatus.success
    assert result.used_fallback is False
    assert result.llm_error_category is None
    assert result.review_error is None

    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.reviewed.value


def test_document_text_is_passed_verbatim_without_additional_trim(db_session):
    raw_text = "  " + NON_VAGUE_TEXT + "  "
    document = make_document(db_session, text=raw_text)
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    workflow.run(UUID(document.id))

    assert fake.calls == [raw_text]


def test_success_path_audit_does_not_contain_full_document_text(db_session):
    distinctive_text = NON_VAGUE_TEXT + " DISTINCTIVE-DOC-MARKER-77f1"
    document = make_document(db_session, text=distinctive_text)
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    result = workflow.run(UUID(document.id))

    stored_audit = db_session.get(AuditRun, str(result.audit_run_id))
    haystack = str(stored_audit.input_json) + str(stored_audit.output_json) + str(stored_audit.error)
    assert "DISTINCTIVE-DOC-MARKER-77f1" not in haystack


# ---------------------------------------------------------------------------
# B. Needs-review path without fallback
# ---------------------------------------------------------------------------


def test_needs_review_without_fallback_persists_needs_review_audit(db_session):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    final_review = _final_review(
        needs_review=True,
        reason_codes=[ReviewReasonCode.MISSING_ACCEPTANCE_CRITERIA],
        acceptance_criteria=[],
    )
    fake = _FakeOrchestrator(result=_orchestration_result(final_review, used_fallback=False))
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    result = workflow.run(UUID(document.id))

    assert result.audit_status == AuditStatus.needs_review
    assert result.used_fallback is False
    assert result.llm_error_category is None
    assert result.review_error is None

    stored_review = db_session.get(Review, str(result.review_id))
    assert stored_review.needs_review == 1
    assert stored_review.reason_codes_json == ["MISSING_ACCEPTANCE_CRITERIA"]
    assert stored_review.error is None

    stored_audit = db_session.get(AuditRun, str(result.audit_run_id))
    assert stored_audit.status == "needs_review"
    assert stored_audit.error is None

    # Manual review is not a technical error: the document is still `reviewed`,
    # never `review_failed` (API_CONTRACTS.md, "Persistence and status outcomes").
    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.reviewed.value


# ---------------------------------------------------------------------------
# C. Safe fallback path, parametrized over every LLMErrorCategory
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("category,root_code", FALLBACK_CATEGORY_ROOT_CODES)
def test_fallback_path_persists_as_error_not_needs_review(db_session, category, root_code):
    """A persisted safe fallback is a *technical* failure, safely contained — it is
    audited as `error` (never `needs_review`), `Review.error`/`audit_runs.error` are
    both non-empty sanitized strings, and `Document.status` becomes `review_failed`
    (API_CONTRACTS.md, "Persistence and status outcomes"). `needs_review=True` alone
    is never sufficient to detect a technical failure — `used_fallback` is."""
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    fallback_review = build_fallback_review(original_text=NON_VAGUE_TEXT, root_reason_code=root_code)
    fake = _FakeOrchestrator(
        result=_orchestration_result(fallback_review, used_fallback=True, llm_error_category=category)
    )
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    result = workflow.run(UUID(document.id))

    assert result.audit_status == AuditStatus.error
    assert result.used_fallback is True
    assert result.llm_error_category == category
    assert result.final_review.needs_review is True
    assert result.review_error
    # The business-facing error is a fixed message and never names the raw
    # LLM error category — the category still lives on, separately, as
    # technical audit metadata (`output_json`, checked below).
    assert category.value not in result.review_error

    stored_review = db_session.get(Review, str(result.review_id))
    assert stored_review.needs_review == 1
    assert root_code.value in stored_review.reason_codes_json
    # Review invariants (task section 7): top-level columns match review_json exactly.
    assert stored_review.confidence == fallback_review.confidence.value
    assert stored_review.readiness == fallback_review.document_readiness.value
    assert stored_review.review_json["needs_review"] is True
    assert bool(stored_review.needs_review) is True
    assert stored_review.error
    assert stored_review.error.strip() == stored_review.error
    assert category.value not in stored_review.error

    stored_audit = db_session.get(AuditRun, str(result.audit_run_id))
    assert stored_audit.status == "error"
    assert stored_audit.error
    assert stored_audit.error.strip() == stored_audit.error
    assert category.value not in stored_audit.error
    assert stored_audit.output_json["used_fallback"] is True
    assert stored_audit.output_json["llm_error_category"] == category.value
    # The category is metadata on the audit row, never folded into the review's own
    # reason codes as a side effect of persistence (regardless of whether the category
    # and its mapped root reason code happen to share the same literal, e.g. INVALID_JSON).
    assert stored_review.reason_codes_json == [code.value for code in fallback_review.review_reason_codes]

    # Persisted safe fallback -> Document.status = review_failed, never left at
    # `created` and never `reviewed` (task section 3.C).
    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.review_failed.value


# ---------------------------------------------------------------------------
# D. JSON round-trip
# ---------------------------------------------------------------------------


def test_json_round_trip_preserves_structure(db_session):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    final_review = _rich_final_review()
    fake = _FakeOrchestrator(result=_orchestration_result(final_review, used_fallback=False))
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    result = workflow.run(UUID(document.id))

    stored_review = db_session.get(Review, str(result.review_id))
    round_tripped = stored_review.review_json

    assert round_tripped == final_review.model_dump(mode="json")
    assert round_tripped["risks"][0]["evidence"] == "Административный API доступен без проверки личности."
    assert round_tripped["risks"][1]["evidence"] is None
    assert round_tripped["contradictions"][0]["evidence"] == [
        "Автосохранение включено по умолчанию.",
        "Автосохранение запрещено политикой.",
    ]
    assert round_tripped["missing_requirements"][0]["category"] == "data"
    assert len(round_tripped["questions_to_client"]) == 2
    assert len(round_tripped["acceptance_criteria"]) == 2
    assert round_tripped["review_reason_codes"] == ["LOW_CONFIDENCE", "CONTRADICTORY_INPUT"]

    rehydrated = FinalReview(**round_tripped)
    assert rehydrated == final_review


# ---------------------------------------------------------------------------
# E. Atomicity
# ---------------------------------------------------------------------------


def test_review_insert_failure_leaves_no_review_or_success_audit(db_session, monkeypatch):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    def _boom(self, **kwargs):
        raise RuntimeError("forced review insert failure")

    monkeypatch.setattr(ReviewRepository, "add", _boom)

    with pytest.raises(RuntimeError, match="forced review insert failure"):
        workflow.run(UUID(document.id))

    assert db_session.in_transaction() is False
    assert db_session.scalar(select(func.count()).select_from(Review)) == 0

    audits = db_session.scalars(select(AuditRun)).all()
    assert len(audits) == 1
    assert audits[0].status == "error"
    assert audits[0].entity_type == "document"
    assert audits[0].entity_id == document.id
    assert audits[0].error == workflow_module._UNEXPECTED_ERROR_AUDIT_MESSAGE

    # No usable review could be stored: the recovery transaction still marks the
    # document `review_failed`, so it is never left stuck at `created`.
    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.review_failed.value


def test_audit_insert_failure_after_review_flush_rolls_back_review(db_session, monkeypatch):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    original_record = AuditService.record
    call_count = {"n": 0}

    def _flaky_record(self, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("forced audit insert failure")
        return original_record(self, **kwargs)

    monkeypatch.setattr(AuditService, "record", _flaky_record)

    with pytest.raises(RuntimeError, match="forced audit insert failure"):
        workflow.run(UUID(document.id))

    assert db_session.in_transaction() is False
    assert db_session.scalar(select(func.count()).select_from(Review)) == 0

    audits = db_session.scalars(select(AuditRun)).all()
    assert len(audits) == 1
    assert audits[0].status == "error"
    assert audits[0].entity_type == "document"
    assert audits[0].entity_id == document.id

    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.review_failed.value


def test_original_error_propagates_even_if_error_audit_write_also_fails(db_session, monkeypatch):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    def _always_boom(self, **kwargs):
        raise RuntimeError("forced audit insert failure")

    monkeypatch.setattr(AuditService, "record", _always_boom)

    with pytest.raises(RuntimeError, match="forced audit insert failure"):
        workflow.run(UUID(document.id))

    assert db_session.in_transaction() is False
    assert db_session.scalar(select(func.count()).select_from(Review)) == 0
    assert db_session.scalar(select(func.count()).select_from(AuditRun)) == 0

    # The recovery audit write itself also failed and was rolled back: the
    # attempted `Document.status` change must not have leaked out either — no
    # partially-consistent state, even though nothing could be audited.
    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.created.value


def test_real_error_audit_flush_failure_does_not_replace_original_exception(db_session, monkeypatch):
    """The error-audit path must degrade gracefully even when it genuinely fails
    inside SQLAlchemy/SQLite (a real `IntegrityError` from the `status` CHECK
    constraint), not merely when a test double raises before touching the DB."""
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    fake = _FakeOrchestrator(exception=RuntimeError("primary workflow failure"))
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    def _write_invalid_row(self, **kwargs):
        audit_run = AuditRunRepository(self._session).add(
            action=kwargs["action"],
            status="not-a-real-status",  # violates ck_audit_runs_status -> real IntegrityError
            duration_ms=kwargs["duration_ms"],
            entity_type=kwargs.get("entity_type"),
            entity_id=kwargs.get("entity_id"),
            input_json=kwargs.get("input_json"),
            output_json=kwargs.get("output_json"),
            error=kwargs.get("error"),
        )
        self._session.flush()
        return audit_run

    monkeypatch.setattr(AuditService, "record", _write_invalid_row)

    with pytest.raises(RuntimeError, match="primary workflow failure"):
        workflow.run(UUID(document.id))

    assert db_session.in_transaction() is False
    assert db_session.scalar(select(func.count()).select_from(AuditRun)) == 0
    # The session must still be usable for a plain, unrelated query afterwards.
    assert db_session.scalar(select(func.count()).select_from(Document)) == 1

    # The recovery write failed for real (IntegrityError) and was rolled back:
    # the attempted `Document.status` change must not have leaked out either.
    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.created.value


def test_main_commit_failure_triggers_recovery_and_reraises_original_exception(db_session, monkeypatch):
    """The main persistence transaction has already flushed `Document` + `Review` +
    `AuditRun` when `session.commit()` itself fails (not `ReviewRepository.add()` or
    `AuditService.record()`, which earlier tests already cover). Uses a per-call
    counter on `db_session.commit` — not a global SQLAlchemy-wide patch — so only the
    session under test is affected: the first `commit()` call (the main transaction)
    fails, `_write_error_audit`'s rollback discards the flushed rows, and its own
    recovery `commit()` (the second call) is allowed to succeed for real."""
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    original_commit = db_session.commit
    call_count = {"n": 0}

    def _flaky_commit():
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("forced main commit failure")
        return original_commit()

    monkeypatch.setattr(db_session, "commit", _flaky_commit)

    with pytest.raises(RuntimeError, match="forced main commit failure"):
        workflow.run(UUID(document.id))

    assert call_count["n"] == 2  # main commit attempted, then the recovery commit
    assert db_session.in_transaction() is False

    # No orphan/partial rows: the main Review (and its success audit) never
    # survived the failed commit.
    assert db_session.scalar(select(func.count()).select_from(Review)) == 0

    audits = db_session.scalars(select(AuditRun)).all()
    assert len(audits) == 1
    assert audits[0].status == "error"
    assert audits[0].entity_type == "document"
    assert audits[0].entity_id == document.id
    assert audits[0].error == workflow_module._UNEXPECTED_ERROR_AUDIT_MESSAGE

    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.review_failed.value

    # The session is not stuck in a failed-transaction state: a plain follow-up
    # query still works.
    assert db_session.scalar(select(func.count()).select_from(Document)) == 1


def test_recovery_commit_failure_after_main_commit_failure_does_not_replace_original_exception(
    db_session, monkeypatch
):
    """Both the main transaction's `commit()` *and* the recovery transaction's own
    final `commit()` fail for real (not `AuditService.record()`, which
    `test_original_error_propagates_even_if_error_audit_write_also_fails` and
    `test_real_error_audit_flush_failure_does_not_replace_original_exception` already
    cover). The recovery rollback must still leave no partial `Document.status`/
    `AuditRun` behind, and the *original* main-commit exception — not whatever the
    recovery commit raised — must be what propagates."""
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    call_count = {"n": 0}

    def _always_boom():
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("forced main commit failure")
        raise RuntimeError("forced recovery commit failure")

    monkeypatch.setattr(db_session, "commit", _always_boom)

    with pytest.raises(RuntimeError, match="forced main commit failure"):
        workflow.run(UUID(document.id))

    assert call_count["n"] == 2  # main commit attempted, then the recovery commit

    assert db_session.in_transaction() is False
    assert db_session.scalar(select(func.count()).select_from(Review)) == 0
    assert db_session.scalar(select(func.count()).select_from(AuditRun)) == 0

    # The recovery commit also failed and was rolled back: the attempted
    # `Document.status` change must not have leaked out either.
    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.created.value

    # The session is still usable afterwards despite both commit failures.
    assert db_session.scalar(select(func.count()).select_from(Document)) == 1


def test_orchestrator_exception_before_persistence_leaves_no_rows(db_session):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    fake = _FakeOrchestrator(exception=RuntimeError("orchestrator exploded"))
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    with pytest.raises(RuntimeError, match="orchestrator exploded"):
        workflow.run(UUID(document.id))

    assert db_session.in_transaction() is False
    assert db_session.scalar(select(func.count()).select_from(Review)) == 0

    audits = db_session.scalars(select(AuditRun)).all()
    assert len(audits) == 1
    assert audits[0].status == "error"
    assert audits[0].entity_type == "document"
    assert audits[0].entity_id == document.id
    assert audits[0].error == workflow_module._UNEXPECTED_ERROR_AUDIT_MESSAGE

    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.review_failed.value


def test_generic_exception_from_orchestrator_is_not_turned_into_fallback(db_session):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    fake = _FakeOrchestrator(exception=ValueError("unexpected bug"))
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    with pytest.raises(ValueError, match="unexpected bug"):
        workflow.run(UUID(document.id))


# ---------------------------------------------------------------------------
# F. Missing document
# ---------------------------------------------------------------------------


def test_missing_document_raises_without_calling_orchestrator_or_persisting(db_session):
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)
    missing_id = uuid.uuid4()

    with pytest.raises(DocumentNotFoundError):
        workflow.run(missing_id)

    assert fake.calls == []
    assert db_session.in_transaction() is False
    assert db_session.scalar(select(func.count()).select_from(Review)) == 0
    assert db_session.scalar(select(func.count()).select_from(AuditRun)) == 0


def test_document_deleted_between_read_and_write_transaction_raises_not_found(db_session):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    orchestrator = _DocumentDeletingOrchestrator(
        session=db_session,
        document_id=document.id,
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False),
    )
    workflow = ReviewWorkflow(session=db_session, orchestrator=orchestrator)

    with pytest.raises(DocumentNotFoundError):
        workflow.run(UUID(document.id))

    assert orchestrator.calls == [NON_VAGUE_TEXT]
    assert db_session.in_transaction() is False
    assert db_session.scalar(select(func.count()).select_from(Review)) == 0
    # No error audit either: this is "no document to review", not a failed attempt.
    assert db_session.scalar(select(func.count()).select_from(AuditRun)) == 0


# ---------------------------------------------------------------------------
# G. Safety: no secrets, exceptions, or provider payloads leak into persisted rows
# ---------------------------------------------------------------------------


def test_dangerous_exception_markers_never_persisted(db_session):
    document = make_document(db_session, text=NON_VAGUE_TEXT + " DISTINCTIVE-DOC-TEXT-MARKER")
    fake = _FakeOrchestrator(exception=RuntimeError(DANGEROUS_ERROR_TEXT))
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    with pytest.raises(RuntimeError):
        workflow.run(UUID(document.id))

    audits = db_session.scalars(select(AuditRun)).all()
    assert len(audits) == 1
    audit = audits[0]

    haystack = str(audit.error) + str(audit.input_json) + str(audit.output_json)
    forbidden_snippets = [
        "sk-test-secret",
        "Authorization: Bearer secret",
        "raw-provider-body",
        "DISTINCTIVE-DOC-TEXT-MARKER",
        DANGEROUS_ERROR_TEXT,
    ]
    for snippet in forbidden_snippets:
        assert snippet not in haystack

    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.review_failed.value


# ---------------------------------------------------------------------------
# H. Version constants
# ---------------------------------------------------------------------------


def test_prompt_and_schema_version_use_imported_constants(db_session):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    result = workflow.run(UUID(document.id))

    stored_audit = db_session.get(AuditRun, str(result.audit_run_id))
    assert PROMPT_VERSION == "spec-review-prompt-v2"
    assert REVIEW_SCHEMA_VERSION == "spec-review-schema-v1"
    assert stored_audit.input_json["prompt_version"] == PROMPT_VERSION
    assert stored_audit.input_json["review_schema_version"] == REVIEW_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# I. Result model contract
# ---------------------------------------------------------------------------


def _sample_success_result() -> PersistedReviewResult:
    return PersistedReviewResult(
        review_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        final_review=_final_review(needs_review=False, reason_codes=[]),
        audit_run_id=uuid.uuid4(),
        audit_status=AuditStatus.success,
        used_fallback=False,
        llm_error_category=None,
    )


def test_result_forbids_additional_fields():
    with pytest.raises(ValidationError):
        PersistedReviewResult(
            review_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            final_review=_final_review(needs_review=False, reason_codes=[]),
            audit_run_id=uuid.uuid4(),
            audit_status=AuditStatus.success,
            used_fallback=False,
            llm_error_category=None,
            unexpected_field="nope",
        )


def test_result_is_frozen():
    result = _sample_success_result()
    with pytest.raises(ValidationError):
        result.used_fallback = True
    with pytest.raises(ValidationError):
        result.audit_status = AuditStatus.needs_review


def test_result_ids_stay_uuid_instances():
    result = _sample_success_result()
    assert isinstance(result.review_id, UUID)
    assert isinstance(result.document_id, UUID)
    assert isinstance(result.audit_run_id, UUID)


def test_result_rejects_error_audit_status_without_fallback():
    """`audit_status='error'` is only valid together with a real `used_fallback=True`
    (task section 4: never derive a technical failure from `needs_review` alone, and
    never fabricate one either)."""
    with pytest.raises(ValidationError):
        PersistedReviewResult(
            review_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            final_review=_final_review(needs_review=False, reason_codes=[]),
            audit_run_id=uuid.uuid4(),
            audit_status=AuditStatus.error,
            used_fallback=False,
            llm_error_category=None,
        )


def test_result_accepts_fallback_with_error_audit_status_and_review_error():
    """The new legal shape for a persisted safe fallback (task section 3.C):
    `used_fallback=True` paired with `audit_status='error'` and a non-empty
    `review_error` must construct successfully, not raise."""
    result = PersistedReviewResult(
        review_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        final_review=_final_review(needs_review=True, reason_codes=[ReviewReasonCode.MODEL_ERROR]),
        audit_run_id=uuid.uuid4(),
        audit_status=AuditStatus.error,
        used_fallback=True,
        llm_error_category=LLMErrorCategory.PROVIDER_ERROR,
        review_error="Проверку не удалось выполнить автоматически. Результат требует экспертной проверки.",
    )
    assert result.audit_status == AuditStatus.error
    assert result.used_fallback is True
    assert result.review_error


def test_result_rejects_fallback_with_empty_review_error():
    with pytest.raises(ValidationError):
        PersistedReviewResult(
            review_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            final_review=_final_review(needs_review=True, reason_codes=[ReviewReasonCode.MODEL_ERROR]),
            audit_run_id=uuid.uuid4(),
            audit_status=AuditStatus.error,
            used_fallback=True,
            llm_error_category=LLMErrorCategory.PROVIDER_ERROR,
            review_error="   ",
        )


def test_result_rejects_fallback_with_missing_review_error():
    with pytest.raises(ValidationError):
        PersistedReviewResult(
            review_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            final_review=_final_review(needs_review=True, reason_codes=[ReviewReasonCode.MODEL_ERROR]),
            audit_run_id=uuid.uuid4(),
            audit_status=AuditStatus.error,
            used_fallback=True,
            llm_error_category=LLMErrorCategory.PROVIDER_ERROR,
            review_error=None,
        )


def test_result_rejects_review_error_without_fallback():
    """A non-null `review_error` is only legal alongside `used_fallback=True`; a
    successful (non-fallback) result must never carry one."""
    with pytest.raises(ValidationError):
        PersistedReviewResult(
            review_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            final_review=_final_review(needs_review=False, reason_codes=[]),
            audit_run_id=uuid.uuid4(),
            audit_status=AuditStatus.success,
            used_fallback=False,
            llm_error_category=None,
            review_error="unexpected error text",
        )


def test_result_rejects_success_status_with_needs_review_true():
    with pytest.raises(ValidationError):
        PersistedReviewResult(
            review_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            final_review=_final_review(needs_review=True, reason_codes=[ReviewReasonCode.LOW_CONFIDENCE]),
            audit_run_id=uuid.uuid4(),
            audit_status=AuditStatus.success,
            used_fallback=False,
            llm_error_category=None,
        )


def test_result_rejects_fallback_true_without_category():
    with pytest.raises(ValidationError):
        PersistedReviewResult(
            review_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            final_review=_final_review(needs_review=True, reason_codes=[ReviewReasonCode.MODEL_ERROR]),
            audit_run_id=uuid.uuid4(),
            audit_status=AuditStatus.needs_review,
            used_fallback=True,
            llm_error_category=None,
        )


def test_result_rejects_category_without_fallback():
    with pytest.raises(ValidationError):
        PersistedReviewResult(
            review_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            final_review=_final_review(needs_review=False, reason_codes=[]),
            audit_run_id=uuid.uuid4(),
            audit_status=AuditStatus.success,
            used_fallback=False,
            llm_error_category=LLMErrorCategory.PROVIDER_ERROR,
        )


def test_result_rejects_fallback_with_success_audit_status():
    with pytest.raises(ValidationError):
        PersistedReviewResult(
            review_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            final_review=_final_review(needs_review=False, reason_codes=[]),
            audit_run_id=uuid.uuid4(),
            audit_status=AuditStatus.success,
            used_fallback=True,
            llm_error_category=LLMErrorCategory.PROVIDER_ERROR,
        )


def test_result_rejects_fallback_with_needs_review_false():
    with pytest.raises(ValidationError):
        PersistedReviewResult(
            review_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            final_review=_final_review(needs_review=False, reason_codes=[]),
            audit_run_id=uuid.uuid4(),
            audit_status=AuditStatus.needs_review,
            used_fallback=True,
            llm_error_category=LLMErrorCategory.PROVIDER_ERROR,
        )


def test_result_rejects_success_with_used_fallback_true():
    with pytest.raises(ValidationError):
        PersistedReviewResult(
            review_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            final_review=_final_review(needs_review=False, reason_codes=[]),
            audit_run_id=uuid.uuid4(),
            audit_status=AuditStatus.success,
            used_fallback=True,
            llm_error_category=LLMErrorCategory.PROVIDER_ERROR,
        )


# ---------------------------------------------------------------------------
# J. Immutable FinalReview snapshot
# ---------------------------------------------------------------------------


def test_result_final_review_is_persisted_final_review_snapshot(db_session):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    final_review = _final_review(needs_review=False, reason_codes=[])
    fake = _FakeOrchestrator(result=_orchestration_result(final_review, used_fallback=False))
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    result = workflow.run(UUID(document.id))

    assert isinstance(result.final_review, PersistedFinalReviewSnapshot)
    assert isinstance(result.final_review, FinalReview)
    assert result.final_review.model_dump(mode="python") == final_review.model_dump(mode="python")


def test_result_final_review_field_assignment_is_rejected(db_session):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    result = workflow.run(UUID(document.id))

    with pytest.raises(ValidationError):
        result.final_review.needs_review = True


def test_snapshot_rejects_extra_fields_like_the_shared_final_review_schema():
    final_review = _final_review(needs_review=False, reason_codes=[])
    with pytest.raises(ValidationError):
        PersistedFinalReviewSnapshot(**final_review.model_dump(mode="python"), unexpected="nope")


# ---------------------------------------------------------------------------
# K. Invalid fallback regression (MAJOR 2)
# ---------------------------------------------------------------------------


def test_invalid_fallback_result_is_rejected_before_persistence(db_session):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    inconsistent_final_review = _final_review(needs_review=False, reason_codes=[])
    invalid_result = _orchestration_result(
        inconsistent_final_review, used_fallback=True, llm_error_category=LLMErrorCategory.PROVIDER_ERROR
    )
    fake = _FakeOrchestrator(result=invalid_result)
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    with pytest.raises(InvalidReviewWorkflowResultError):
        workflow.run(UUID(document.id))

    assert db_session.in_transaction() is False
    assert db_session.scalar(select(func.count()).select_from(Review)) == 0

    audits = db_session.scalars(select(AuditRun)).all()
    assert len(audits) == 1
    assert audits[0].status == "error"
    assert audits[0].entity_type == "document"
    assert audits[0].entity_id == document.id
    assert audits[0].error == workflow_module._UNEXPECTED_ERROR_AUDIT_MESSAGE

    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.review_failed.value


# ---------------------------------------------------------------------------
# K2. Corrupted orchestration result (recovery boundary hardening)
#
# A non-conforming injected orchestrator can bypass Pydantic validation entirely
# by constructing a `ReviewOrchestrationResult` via `model_construct(...)`. These
# tests prove such a result is never trusted just because it is annotated with
# that type, and that every failure path here (missing category, wrong category
# type, and a downstream `final_review` snapshot-validation failure) is handled by
# the same "no usable review" recovery boundary as any other unexpected failure —
# never a bare, unhandled `AttributeError`/`ValidationError` outside it.
# ---------------------------------------------------------------------------


def test_missing_category_on_used_fallback_is_treated_as_no_usable_review(db_session):
    """`used_fallback=True` with `llm_error_category=None`, bypassing the
    `ReviewOrchestrationResult` validator via `model_construct(...)`: must never
    reach `.value` (a bare `AttributeError`), and must be rejected before any
    `Review`/`AuditRun` row referencing a review is created."""
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    valid_final_review = _final_review(needs_review=True, reason_codes=[ReviewReasonCode.MODEL_ERROR])
    corrupted_result = ReviewOrchestrationResult.model_construct(
        final_review=valid_final_review,
        used_fallback=True,
        llm_error_category=None,
    )
    fake = _FakeOrchestrator(result=corrupted_result)
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    with pytest.raises(InvalidReviewWorkflowResultError):
        workflow.run(UUID(document.id))

    assert db_session.in_transaction() is False
    assert db_session.scalar(select(func.count()).select_from(Review)) == 0

    audits = db_session.scalars(select(AuditRun)).all()
    assert len(audits) == 1
    assert audits[0].status == "error"
    assert audits[0].entity_type == "document"
    assert audits[0].entity_id == document.id
    assert audits[0].error == workflow_module._UNEXPECTED_ERROR_AUDIT_MESSAGE

    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.review_failed.value


@pytest.mark.parametrize(
    "bogus_category",
    [
        pytest.param("PROVIDER_ERROR", id="raw_string"),
        pytest.param(object(), id="unrelated_object"),
        pytest.param(123, id="int"),
    ],
)
def test_unexpected_category_type_is_treated_as_no_usable_review(db_session, bogus_category):
    """A category value that bypassed `LLMErrorCategory` enum validation (wrong
    type, or a plain string that merely matches a member's literal value) must
    never be treated as if it were a real `LLMErrorCategory` member, and must
    never leak its raw value into the persisted recovery error message."""
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    valid_final_review = _final_review(needs_review=True, reason_codes=[ReviewReasonCode.MODEL_ERROR])
    corrupted_result = ReviewOrchestrationResult.model_construct(
        final_review=valid_final_review,
        used_fallback=True,
        llm_error_category=bogus_category,
    )
    fake = _FakeOrchestrator(result=corrupted_result)
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    with pytest.raises(InvalidReviewWorkflowResultError):
        workflow.run(UUID(document.id))

    assert db_session.in_transaction() is False
    assert db_session.scalar(select(func.count()).select_from(Review)) == 0

    audits = db_session.scalars(select(AuditRun)).all()
    assert len(audits) == 1
    assert audits[0].status == "error"
    assert audits[0].error == workflow_module._UNEXPECTED_ERROR_AUDIT_MESSAGE
    assert "PROVIDER_ERROR" not in (audits[0].error or "")

    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.review_failed.value


def test_snapshot_validation_failure_after_orchestration_result_is_treated_as_no_usable_review(
    db_session, monkeypatch
):
    """Simulates a `final_review` re-validation (snapshot) failure discovered only
    after `orchestrator.review(...)` already returned. Before the recovery-boundary
    fix, this code ran *between* the two `try` blocks and any failure here escaped
    completely unhandled (no rollback, no recovery audit, no `Document.status`
    update); it must now be indistinguishable from any other unexpected failure."""
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    def _boom(final_review):
        raise ValueError("forced snapshot validation failure")

    monkeypatch.setattr(workflow_module, "_snapshot_final_review", _boom)

    with pytest.raises(ValueError, match="forced snapshot validation failure"):
        workflow.run(UUID(document.id))

    assert db_session.in_transaction() is False
    assert db_session.scalar(select(func.count()).select_from(Review)) == 0

    audits = db_session.scalars(select(AuditRun)).all()
    assert len(audits) == 1
    assert audits[0].status == "error"
    assert audits[0].entity_type == "document"
    assert audits[0].entity_id == document.id
    assert audits[0].error == workflow_module._UNEXPECTED_ERROR_AUDIT_MESSAGE

    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.review_failed.value

    # Recovery left the session usable: a plain follow-up query still works.
    assert db_session.scalar(select(func.count()).select_from(Document)) == 1


@pytest.mark.parametrize(
    "bogus_used_fallback",
    [
        pytest.param(1, id="int_one"),
        pytest.param("true", id="raw_string_true"),
        pytest.param(None, id="none"),
        pytest.param(object(), id="unrelated_object"),
    ],
)
def test_used_fallback_of_wrong_type_is_treated_as_no_usable_review(db_session, bogus_used_fallback):
    """Direct regression for the runtime guard `isinstance(result.used_fallback, bool)`
    inside `_validate_orchestration_result` (not a monkeypatch of the validator
    itself). `ReviewOrchestrationResult.used_fallback` is declared `StrictBool`, but a
    non-conforming injected orchestrator can bypass that entirely via
    `model_construct(...)` and hand back a value that only *looks* like a bool
    truth-value (`1`, the string `"true"`, `None`, an arbitrary object) — none of
    these are `isinstance(..., bool)`, so none may be trusted as the real flag that
    decides `Review.error`/`AuditRun.status`/`Document.status`."""
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    valid_final_review = _final_review(needs_review=False, reason_codes=[])
    corrupted_result = ReviewOrchestrationResult.model_construct(
        final_review=valid_final_review,
        used_fallback=bogus_used_fallback,
        llm_error_category=None,
    )
    fake = _FakeOrchestrator(result=corrupted_result)
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    with pytest.raises(InvalidReviewWorkflowResultError):
        workflow.run(UUID(document.id))

    assert db_session.in_transaction() is False
    assert db_session.scalar(select(func.count()).select_from(Review)) == 0

    audits = db_session.scalars(select(AuditRun)).all()
    assert len(audits) == 1
    assert audits[0].status == "error"
    assert audits[0].entity_type == "document"
    assert audits[0].entity_id == document.id
    assert audits[0].error  # non-empty
    assert audits[0].error == workflow_module._UNEXPECTED_ERROR_AUDIT_MESSAGE

    # The raw invalid value must never leak into `AuditRun.error` specifically —
    # the exact-match assertion above already guarantees this on its own (the
    # message is a fixed constant with no dynamic content), and this re-checks it
    # explicitly by scanning only `error` (not `input_json`/`output_json`, which
    # legitimately contain the literal text "None" for the unrelated
    # `llm_error_category` metadata field and would otherwise false-positive for
    # `bogus_used_fallback=None`).
    assert repr(bogus_used_fallback) not in audits[0].error

    # Read the actual persisted state back from the database (not the in-memory
    # ORM object still held from `make_document`): expire the identity map first
    # so `.get(...)` is forced to re-SELECT.
    db_session.expire_all()
    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.review_failed.value

    # Recovery left the session usable for further queries.
    assert db_session.scalar(select(func.count()).select_from(Document)) == 1


# ---------------------------------------------------------------------------
# K3. Malformed final_review (recovery boundary hardening, direct malformed-data path)
# ---------------------------------------------------------------------------


def test_final_review_of_wrong_type_is_treated_as_no_usable_review(db_session):
    """`final_review=object()`: not even a `FinalReview` instance, bypassing the
    `ReviewOrchestrationResult` Pydantic validator entirely via
    `model_construct(...)`. Must be rejected by `isinstance(result.final_review,
    FinalReview)` before any attribute access (`.needs_review`) or DB write, and
    the object's `repr()` must never leak into the persisted recovery message."""
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    bogus_final_review = object()
    corrupted_result = ReviewOrchestrationResult.model_construct(
        final_review=bogus_final_review,
        used_fallback=False,
        llm_error_category=None,
    )
    fake = _FakeOrchestrator(result=corrupted_result)
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    with pytest.raises(InvalidReviewWorkflowResultError):
        workflow.run(UUID(document.id))

    assert db_session.in_transaction() is False
    assert db_session.scalar(select(func.count()).select_from(Review)) == 0

    audits = db_session.scalars(select(AuditRun)).all()
    assert len(audits) == 1
    assert audits[0].status == "error"
    assert audits[0].entity_type == "document"
    assert audits[0].entity_id == document.id
    assert audits[0].error
    assert audits[0].error == workflow_module._UNEXPECTED_ERROR_AUDIT_MESSAGE

    haystack = str(audits[0].error) + str(audits[0].input_json) + str(audits[0].output_json)
    assert repr(bogus_final_review) not in haystack
    assert "object at 0x" not in haystack

    db_session.expire_all()
    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.review_failed.value

    assert db_session.scalar(select(func.count()).select_from(Document)) == 1


def test_structurally_malformed_final_review_fails_snapshot_and_is_treated_as_no_usable_review(db_session):
    """A `FinalReview` built via `FinalReview.model_construct(...)` *is* a real
    `FinalReview` instance (passes `isinstance`), but carries a `confidence` value
    that was never validated against the closed `ReviewConfidence` enum — the kind
    of malformed data a non-conforming orchestrator's fallback/parsing code could
    produce. This is a direct exercise of the actual malformed-data path through
    `_snapshot_final_review` (`PersistedFinalReviewSnapshot.model_validate(...)`)
    itself, not a monkeypatch replacing that function (see
    `test_snapshot_validation_failure_after_orchestration_result_is_treated_as_no_usable_review`
    above, which proves the *boundary*; this test proves the *real validation path*
    inside it also fails safely on genuinely malformed data)."""
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    malformed_final_review = FinalReview.model_construct(
        summary="Summary of the reviewed specification.",
        risks=[],
        missing_requirements=[],
        contradictions=[],
        questions_to_client=["Question one?", "Question two?", "Question three?"],
        acceptance_criteria=["Given X, when Y, then Z."],
        confidence="not-a-real-confidence-level",  # not a ReviewConfidence member
        document_readiness="ready",
        needs_review=True,
        review_reason_codes=[ReviewReasonCode.MODEL_ERROR],
    )
    assert isinstance(malformed_final_review, FinalReview)  # passes isinstance, still malformed

    corrupted_result = ReviewOrchestrationResult.model_construct(
        final_review=malformed_final_review,
        used_fallback=False,
        llm_error_category=None,
    )
    fake = _FakeOrchestrator(result=corrupted_result)
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    with pytest.raises(ValidationError):
        workflow.run(UUID(document.id))

    assert db_session.in_transaction() is False
    assert db_session.scalar(select(func.count()).select_from(Review)) == 0

    audits = db_session.scalars(select(AuditRun)).all()
    assert len(audits) == 1
    assert audits[0].status == "error"
    assert audits[0].entity_type == "document"
    assert audits[0].entity_id == document.id
    assert audits[0].error
    assert audits[0].error == workflow_module._UNEXPECTED_ERROR_AUDIT_MESSAGE

    # The raw invalid field value and Pydantic's own validation-error internals
    # must never leak into the persisted recovery message.
    haystack = str(audits[0].error) + str(audits[0].input_json) + str(audits[0].output_json)
    assert "not-a-real-confidence-level" not in haystack
    assert "ValidationError" not in haystack

    db_session.expire_all()
    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.review_failed.value

    assert db_session.scalar(select(func.count()).select_from(Document)) == 1


# ---------------------------------------------------------------------------
# L. Denormalized Review columns vs. review_json vs. source FinalReview
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "final_review",
    [
        pytest.param(_final_review(needs_review=False, reason_codes=[]), id="success"),
        pytest.param(
            _final_review(
                needs_review=True,
                reason_codes=[ReviewReasonCode.LOW_CONFIDENCE, ReviewReasonCode.MISSING_ACCEPTANCE_CRITERIA],
                acceptance_criteria=[],
                confidence="low",
            ),
            id="needs_review",
        ),
    ],
)
def test_denormalized_review_columns_match_review_json_and_source_final_review(db_session, final_review):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    fake = _FakeOrchestrator(result=_orchestration_result(final_review, used_fallback=False))
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    result = workflow.run(UUID(document.id))

    stored_review = db_session.get(Review, str(result.review_id))
    review_json = stored_review.review_json

    assert stored_review.confidence == final_review.confidence.value == review_json["confidence"]
    assert (
        stored_review.readiness
        == final_review.document_readiness.value
        == review_json["document_readiness"]
    )
    assert bool(stored_review.needs_review) is final_review.needs_review
    assert bool(stored_review.needs_review) is review_json["needs_review"]
    expected_codes = [code.value for code in final_review.review_reason_codes]
    assert stored_review.reason_codes_json == expected_codes
    assert review_json["review_reason_codes"] == expected_codes


# ---------------------------------------------------------------------------
# M. Result usable after session.close()
# ---------------------------------------------------------------------------


def test_result_usable_after_session_close(db_session):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    final_review = _final_review(needs_review=False, reason_codes=[])
    fake = _FakeOrchestrator(result=_orchestration_result(final_review, used_fallback=False))
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    result = workflow.run(UUID(document.id))
    db_session.close()

    dumped = result.model_dump()
    json_dumped = result.model_dump(mode="json")

    assert dumped["review_id"] == result.review_id
    assert dumped["final_review"]["needs_review"] is False
    assert json_dumped["review_id"] == str(result.review_id)
    assert json_dumped["document_id"] == str(result.document_id)
    assert json_dumped["final_review"]["summary"] == final_review.summary
    assert json_dumped["audit_status"] == "success"
    assert isinstance(result.final_review, FinalReview)


# ---------------------------------------------------------------------------
# N. Repeated run
# ---------------------------------------------------------------------------


def test_repeated_run_creates_independent_rows(db_session):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    first = workflow.run(UUID(document.id))
    assert db_session.in_transaction() is False

    second = workflow.run(UUID(document.id))
    assert db_session.in_transaction() is False

    assert first.review_id != second.review_id
    assert first.audit_run_id != second.audit_run_id
    assert first.document_id == second.document_id == UUID(document.id)

    reviews_count = db_session.scalar(
        select(func.count()).select_from(Review).where(Review.document_id == document.id)
    )
    assert reviews_count == 2
    assert db_session.get(Review, str(first.review_id)) is not None
    assert db_session.get(Review, str(second.review_id)) is not None
    assert db_session.get(AuditRun, str(first.audit_run_id)) is not None
    assert db_session.get(AuditRun, str(second.audit_run_id)) is not None

    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.reviewed.value


def test_repeated_run_after_fallback_recovers_document_status_to_reviewed(db_session):
    """task section 8, "Повторный review после review_failed": a fallback run
    leaves `Document.status=review_failed`; a later successful retry against the
    same document must move it back to `reviewed`, create an independent second
    `Review`/`AuditRun` pair, and leave the first (fallback) `Review` row untouched."""
    document = make_document(db_session, text=NON_VAGUE_TEXT)

    fallback_review = build_fallback_review(
        original_text=NON_VAGUE_TEXT, root_reason_code=ReviewReasonCode.MODEL_ERROR
    )
    failing_fake = _FakeOrchestrator(
        result=_orchestration_result(
            fallback_review, used_fallback=True, llm_error_category=LLMErrorCategory.TRANSPORT_ERROR
        )
    )
    workflow = ReviewWorkflow(session=db_session, orchestrator=failing_fake)

    first = workflow.run(UUID(document.id))
    assert first.audit_status == AuditStatus.error
    assert db_session.get(Document, document.id).status == DocumentStatus.review_failed.value

    succeeding_fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    workflow_retry = ReviewWorkflow(session=db_session, orchestrator=succeeding_fake)

    second = workflow_retry.run(UUID(document.id))

    assert second.audit_status == AuditStatus.success
    assert second.review_id != first.review_id
    assert second.audit_run_id != first.audit_run_id

    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.reviewed.value

    # The earlier fallback Review/AuditRun rows are still present and unmodified,
    # not overwritten or deleted by the successful retry.
    first_review = db_session.get(Review, str(first.review_id))
    assert first_review is not None
    assert first_review.error
    first_audit = db_session.get(AuditRun, str(first.audit_run_id))
    assert first_audit is not None
    assert first_audit.status == "error"

    second_review = db_session.get(Review, str(second.review_id))
    assert second_review is not None
    assert second_review.error is None

    reviews_count = db_session.scalar(
        select(func.count()).select_from(Review).where(Review.document_id == document.id)
    )
    assert reviews_count == 2


# ---------------------------------------------------------------------------
# O. Transaction boundary
# ---------------------------------------------------------------------------


def test_no_open_transaction_during_orchestrator_call(db_session):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False),
        track_session=db_session,
    )
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    workflow.run(UUID(document.id))

    assert fake.in_transaction_snapshots == [False]


def test_session_not_in_transaction_after_missing_document(db_session):
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    with pytest.raises(DocumentNotFoundError):
        workflow.run(uuid.uuid4())

    assert db_session.in_transaction() is False


def test_session_not_in_transaction_after_successful_run(db_session):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    workflow.run(UUID(document.id))

    assert db_session.in_transaction() is False


def test_session_not_in_transaction_after_orchestrator_runtime_error(db_session):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    fake = _FakeOrchestrator(exception=RuntimeError("boom"))
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    with pytest.raises(RuntimeError, match="boom"):
        workflow.run(UUID(document.id))

    assert db_session.in_transaction() is False


# ---------------------------------------------------------------------------
# P. BaseException is never caught
# ---------------------------------------------------------------------------


def test_keyboard_interrupt_from_orchestrator_propagates_and_closes_transaction(db_session):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    fake = _FakeOrchestrator(exception=KeyboardInterrupt())
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    with pytest.raises(KeyboardInterrupt):
        workflow.run(UUID(document.id))

    assert db_session.in_transaction() is False
    assert db_session.scalar(select(func.count()).select_from(AuditRun)) == 0


def test_system_exit_from_orchestrator_propagates_and_closes_transaction(db_session):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    fake = _FakeOrchestrator(exception=SystemExit())
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    with pytest.raises(SystemExit):
        workflow.run(UUID(document.id))

    assert db_session.in_transaction() is False
    assert db_session.scalar(select(func.count()).select_from(AuditRun)) == 0


def test_generator_exit_from_orchestrator_propagates_and_closes_transaction(db_session):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    fake = _FakeOrchestrator(exception=GeneratorExit())
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    with pytest.raises(GeneratorExit):
        workflow.run(UUID(document.id))

    assert db_session.in_transaction() is False
    assert db_session.scalar(select(func.count()).select_from(AuditRun)) == 0

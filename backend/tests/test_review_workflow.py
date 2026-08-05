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

from app.enums import AuditStatus, LLMErrorCategory, ReviewReasonCode
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
    assert stored_audit.input_json["prompt_version"] == "spec-review-prompt-v1"
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

    stored_review = db_session.get(Review, str(result.review_id))
    assert stored_review.needs_review == 1
    assert stored_review.reason_codes_json == ["MISSING_ACCEPTANCE_CRITERIA"]

    stored_audit = db_session.get(AuditRun, str(result.audit_run_id))
    assert stored_audit.status == "needs_review"
    assert stored_audit.error is None


# ---------------------------------------------------------------------------
# C. Safe fallback path, parametrized over every LLMErrorCategory
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("category,root_code", FALLBACK_CATEGORY_ROOT_CODES)
def test_fallback_path_persists_as_needs_review_not_error(db_session, category, root_code):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    fallback_review = build_fallback_review(original_text=NON_VAGUE_TEXT, root_reason_code=root_code)
    fake = _FakeOrchestrator(
        result=_orchestration_result(fallback_review, used_fallback=True, llm_error_category=category)
    )
    workflow = ReviewWorkflow(session=db_session, orchestrator=fake)

    result = workflow.run(UUID(document.id))

    assert result.audit_status == AuditStatus.needs_review
    assert result.used_fallback is True
    assert result.llm_error_category == category
    assert result.final_review.needs_review is True

    stored_review = db_session.get(Review, str(result.review_id))
    assert stored_review.needs_review == 1
    assert root_code.value in stored_review.reason_codes_json

    stored_audit = db_session.get(AuditRun, str(result.audit_run_id))
    assert stored_audit.status == "needs_review"
    assert stored_audit.error is None
    assert stored_audit.output_json["used_fallback"] is True
    assert stored_audit.output_json["llm_error_category"] == category.value
    # The category is metadata on the audit row, never folded into the review's own
    # reason codes as a side effect of persistence (regardless of whether the category
    # and its mapped root reason code happen to share the same literal, e.g. INVALID_JSON).
    assert stored_review.reason_codes_json == [code.value for code in fallback_review.review_reason_codes]
    assert stored_audit.error is None


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
    assert PROMPT_VERSION == "spec-review-prompt-v1"
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


def test_result_rejects_error_audit_status():
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

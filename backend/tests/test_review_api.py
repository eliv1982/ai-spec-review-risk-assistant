"""Offline API tests for the review HTTP endpoints:

    POST /api/documents/{document_id}/review  -> ReviewWorkflow -> persisted Review + AuditRun
    POST /api/ai/review                       -> ReviewOrchestrator -> FinalReview, no persistence

No test here touches the network, the real OpenAI SDK, or a real `OPENAI_API_KEY`.
Most tests override `app.api.deps.get_review_orchestrator` (or, for `/api/ai/review`,
`app.api.deps.get_ai_review_service`) with an injected fake, while still exercising
the real `ReviewWorkflow` / `AIReviewService` and the isolated temp SQLite database
from `tests/conftest.py`. A few dedicated "wiring" tests instead override only
`app.api.deps.get_review_client` with a fake LLM client, so the real
`ReviewOrchestrator` and `ReviewWorkflow`/`AIReviewService` run end to end, proving
the production dependency graph (not just an arbitrarily mocked router) is wired
correctly.
"""

import json
import os
import uuid
from typing import List, Optional

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

import app.services.ai_review_service as ai_review_service_module
from app.api.deps import (
    get_ai_review_service,
    get_configured_model_name,
    get_review_client,
    get_review_orchestrator,
    get_review_workflow,
)
from app.enums import DocumentStatus, LLMErrorCategory, ReviewReasonCode
from app.llm.errors import LLMTransportError
from app.llm.prompts import PROMPT_VERSION, REVIEW_SCHEMA_VERSION
from app.main import app
from app.models import AuditRun, Document, Review
from app.repositories.audit_repository import AuditRunRepository
from app.schemas.review import AIReviewRequest, FinalReview, ModelReviewDraft
from app.services.ai_review_service import AIReviewService
from app.services.audit_service import AuditService
from app.services.review_orchestrator import ReviewOrchestrationResult
from app.services.review_qc import build_fallback_review
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
    'raw-provider-body {"secret": "leak"} returned; ' + NON_VAGUE_TEXT
)

VALID_DRAFT_KWARGS = dict(
    summary="Summary of the reviewed specification.",
    risks=[],
    missing_requirements=[],
    contradictions=[],
    questions_to_client=["Question one?", "Question two?", "Question three?"],
    acceptance_criteria=["Given X, when Y, then Z."],
    confidence="high",
    document_readiness="ready",
    model_needs_review=False,
)


@pytest.fixture(autouse=True)
def _reset_dependency_overrides():
    yield
    app.dependency_overrides.clear()


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


class _FakeOrchestrator:
    """Injected fake satisfying `ReviewOrchestratorProtocol`; never touches an LLM."""

    def __init__(
        self,
        *,
        result: Optional[ReviewOrchestrationResult] = None,
        exception: Optional[BaseException] = None,
    ) -> None:
        self._result = result
        self._exception = exception
        self.calls: List[str] = []

    def review(self, document_text: str) -> ReviewOrchestrationResult:
        self.calls.append(document_text)
        if self._exception is not None:
            raise self._exception
        assert self._result is not None
        return self._result


class _FakeLLMClient:
    """Injected fake satisfying `app.services.review_orchestrator.ReviewClient`.

    Used only by the wiring tests (section M): overriding `get_review_client`
    with this fake, while leaving `get_review_orchestrator` un-overridden, proves
    the real `ReviewOrchestrator` (and, transitively, the real `ReviewWorkflow` /
    `AIReviewService`) are wired correctly end to end.
    """

    def __init__(
        self,
        *,
        draft: Optional[ModelReviewDraft] = None,
        exception: Optional[BaseException] = None,
    ) -> None:
        self._draft = draft
        self._exception = exception
        self.calls: List[str] = []

    def review(self, document_text: str) -> ModelReviewDraft:
        self.calls.append(document_text)
        if self._exception is not None:
            raise self._exception
        assert self._draft is not None
        return self._draft


class _TrackingOrchestrator:
    """Records `session.in_transaction()` at call time (section 6: the orchestrator
    call itself must run outside any open transaction)."""

    def __init__(self, *, result: ReviewOrchestrationResult, session) -> None:
        self._result = result
        self._session = session
        self.in_transaction_snapshots: List[bool] = []

    def review(self, document_text: str) -> ReviewOrchestrationResult:
        self.in_transaction_snapshots.append(self._session.in_transaction())
        return self._result


def _document_review_audit(db_session, review_id: str) -> AuditRun:
    return db_session.execute(
        select(AuditRun).where(AuditRun.action == "document.review", AuditRun.entity_id == review_id)
    ).scalar_one()


def _ai_review_audits(db_session) -> List[AuditRun]:
    return list(db_session.scalars(select(AuditRun).where(AuditRun.action == "ai.review")).all())


# ---------------------------------------------------------------------------
# A. Route registration
# ---------------------------------------------------------------------------


def test_document_review_route_is_registered_as_post_only(client):
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]["/api/documents/{document_id}/review"].keys()) == {"post"}

    # A GET on the same path must not be dispatched to this handler.
    response = client.get(f"/api/documents/{uuid.uuid4()}/review")
    assert response.status_code == 405


def test_ai_review_route_is_registered_as_post_only(client):
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]["/api/ai/review"].keys()) == {"post"}

    response = client.get("/api/ai/review")
    assert response.status_code == 405


def test_document_review_appears_in_openapi(client):
    schema = client.get("/openapi.json").json()
    assert "/api/documents/{document_id}/review" in schema["paths"]
    operation = schema["paths"]["/api/documents/{document_id}/review"]["post"]
    assert "201" in operation["responses"]


def test_ai_review_appears_in_openapi(client):
    schema = client.get("/openapi.json").json()
    assert "/api/ai/review" in schema["paths"]
    operation = schema["paths"]["/api/ai/review"]["post"]
    assert "200" in operation["responses"]


# ---------------------------------------------------------------------------
# B. Document review success
# ---------------------------------------------------------------------------


def test_document_review_success(client, db_session):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    final_review = _final_review(needs_review=False, reason_codes=[])
    fake = _FakeOrchestrator(result=_orchestration_result(final_review, used_fallback=False))
    app.dependency_overrides[get_review_orchestrator] = lambda: fake

    response = client.post(f"/api/documents/{document.id}/review")

    assert response.status_code == 201
    body = response.json()
    assert fake.calls == [document.text]

    stored_review = db_session.get(Review, body["id"])
    assert stored_review is not None
    assert stored_review.document_id == document.id
    assert body["document_id"] == document.id
    assert body["confidence"] == "high"
    assert body["readiness"] == "ready"
    assert body["needs_review"] is False
    assert body["reason_codes"] == []
    assert body["error"] is None
    assert body["review_json"]["summary"] == final_review.summary

    audit = _document_review_audit(db_session, body["id"])
    assert audit.status == "success"
    assert audit.error is None
    assert audit.output_json["used_fallback"] is False
    assert audit.output_json["llm_error_category"] is None

    # The HTTP request committed through a separate request-scoped `Session`;
    # `expire_all()` forces this test session to re-read from the database
    # instead of returning its own stale cached `Document` instance.
    db_session.expire_all()
    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.reviewed.value

    document_response = client.get(f"/api/documents/{document.id}")
    assert document_response.json()["status"] == "reviewed"


def test_document_review_orchestrator_called_exactly_once_with_stored_text(client, db_session):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    app.dependency_overrides[get_review_orchestrator] = lambda: fake

    client.post(f"/api/documents/{document.id}/review")

    assert fake.calls == [document.text]


# ---------------------------------------------------------------------------
# C. Needs-review without fallback
# ---------------------------------------------------------------------------


def test_document_review_needs_review_without_fallback(client, db_session):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    final_review = _final_review(
        needs_review=True,
        reason_codes=[ReviewReasonCode.MISSING_ACCEPTANCE_CRITERIA],
        acceptance_criteria=[],
    )
    fake = _FakeOrchestrator(result=_orchestration_result(final_review, used_fallback=False))
    app.dependency_overrides[get_review_orchestrator] = lambda: fake

    response = client.post(f"/api/documents/{document.id}/review")

    assert response.status_code == 201
    body = response.json()
    assert body["needs_review"] is True
    assert body["reason_codes"] == ["MISSING_ACCEPTANCE_CRITERIA"]
    assert body["error"] is None

    audit = _document_review_audit(db_session, body["id"])
    assert audit.status == "needs_review"
    assert audit.error is None
    assert audit.output_json["used_fallback"] is False

    # Manual review is not a technical error: the document is still `reviewed`.
    # The HTTP request committed through a separate request-scoped `Session`;
    # `expire_all()` forces this test session to re-read from the database
    # instead of returning its own stale cached `Document` instance.
    db_session.expire_all()
    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.reviewed.value


# ---------------------------------------------------------------------------
# D. Safe fallback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "category,root_code",
    [
        pytest.param(LLMErrorCategory.API_ERROR, ReviewReasonCode.MODEL_ERROR, id="api_error"),
        pytest.param(LLMErrorCategory.INVALID_JSON, ReviewReasonCode.INVALID_JSON, id="invalid_json"),
        pytest.param(LLMErrorCategory.SCHEMA_MISMATCH, ReviewReasonCode.SCHEMA_MISMATCH, id="schema_mismatch"),
    ],
)
def test_document_review_safe_fallback_returns_normal_success_response(client, db_session, category, root_code):
    """A persisted safe fallback is still returned as a normal `201` (never a
    `5xx`/`502`), but — unlike a genuine successful review — carries a non-empty
    `error`, is audited as `status="error"`, and moves the document to
    `review_failed` (task section 3.C / API_CONTRACTS.md)."""
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    fallback_review = build_fallback_review(original_text=NON_VAGUE_TEXT, root_reason_code=root_code)
    fake = _FakeOrchestrator(
        result=_orchestration_result(fallback_review, used_fallback=True, llm_error_category=category)
    )
    app.dependency_overrides[get_review_orchestrator] = lambda: fake

    response = client.post(f"/api/documents/{document.id}/review")

    assert response.status_code == 201
    body = response.json()
    assert body["needs_review"] is True
    assert root_code.value in body["reason_codes"]
    assert body["error"]
    # The business-facing error is a fixed message and never names the raw
    # LLM error category (task: "API_ERROR, CONFIGURATION_ERROR... показывать
    # только в служебном/техническом блоке") — the category still lives on,
    # separately, as technical audit metadata (`output_json`, below).
    assert category.value not in body["error"]
    assert body["error"] == "Проверку не удалось выполнить автоматически. Результат требует экспертной проверки."

    audit = _document_review_audit(db_session, body["id"])
    assert audit.status == "error"
    assert audit.error
    assert category.value not in audit.error
    assert audit.output_json["used_fallback"] is True
    assert audit.output_json["llm_error_category"] == category.value

    # The HTTP request committed through a separate request-scoped `Session`;
    # `expire_all()` forces this test session to re-read from the database
    # instead of returning its own stale cached `Document` instance.
    db_session.expire_all()
    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.review_failed.value

    # GET the persisted review back: the fallback's `error` and `needs_review`
    # survive a fresh read, not just the original POST response.
    review_get = client.get(f"/api/reviews/{body['id']}")
    assert review_get.status_code == 200
    review_body = review_get.json()
    assert review_body["needs_review"] is True
    assert review_body["error"]
    assert category.value not in review_body["error"]

    # GET the audit log back filtered to errors: the fallback's audit row is
    # discoverable through the same `errors_only=true` query the frontend audit
    # journal uses.
    audit_list = client.get("/api/audit-runs", params={"errors_only": "true"})
    assert audit_list.status_code == 200
    audit_ids = [item["id"] for item in audit_list.json()["items"]]
    assert audit.id in audit_ids

    # GET the document back: `review_failed` survives a fresh read too.
    document_get = client.get(f"/api/documents/{document.id}")
    assert document_get.status_code == 200
    assert document_get.json()["status"] == "review_failed"


# ---------------------------------------------------------------------------
# E. Missing document
# ---------------------------------------------------------------------------


def test_document_review_missing_document_returns_404(client):
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    app.dependency_overrides[get_review_orchestrator] = lambda: fake
    missing_id = uuid.uuid4()

    response = client.post(f"/api/documents/{missing_id}/review")

    assert response.status_code == 404
    body = response.json()
    assert "detail" in body
    assert body["detail"]
    assert fake.calls == []


def test_document_review_missing_document_does_not_persist_or_call_orchestrator(client, db_session):
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    app.dependency_overrides[get_review_orchestrator] = lambda: fake

    response = client.post(f"/api/documents/{uuid.uuid4()}/review")

    assert response.status_code == 404
    assert fake.calls == []
    assert db_session.scalar(select(func.count()).select_from(Review)) == 0
    assert db_session.scalar(select(func.count()).select_from(AuditRun)) == 0


def test_document_review_missing_document_does_not_require_openai_api_key(client):
    """No dependency override at all: proves the 404 path never reaches the LLM client."""
    assert os.environ.get("OPENAI_API_KEY", "") == ""

    response = client.post(f"/api/documents/{uuid.uuid4()}/review")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# F. Invalid UUID
# ---------------------------------------------------------------------------


def test_document_review_invalid_uuid_returns_422(client, db_session):
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    app.dependency_overrides[get_review_orchestrator] = lambda: fake

    response = client.post("/api/documents/not-a-uuid/review")

    assert response.status_code == 422
    assert fake.calls == []
    assert db_session.scalar(select(func.count()).select_from(Review)) == 0
    assert db_session.scalar(select(func.count()).select_from(AuditRun)) == 0


# ---------------------------------------------------------------------------
# G. Fatal workflow error
# ---------------------------------------------------------------------------


def test_document_review_fatal_error_returns_500_without_leaking_secrets(client, db_session):
    document = make_document(db_session, text=DANGEROUS_ERROR_TEXT)
    fake = _FakeOrchestrator(exception=RuntimeError(DANGEROUS_ERROR_TEXT))
    app.dependency_overrides[get_review_orchestrator] = lambda: fake

    response = client.post(f"/api/documents/{document.id}/review")

    assert response.status_code == 500
    raw_body = response.text
    for secret in (
        "sk-test-secret",
        "Authorization: Bearer secret",
        "raw-provider-body",
        DANGEROUS_ERROR_TEXT,
        NON_VAGUE_TEXT,
    ):
        assert secret not in raw_body

    assert db_session.scalar(select(func.count()).select_from(Review)) == 0

    audits = db_session.scalars(
        select(AuditRun).where(AuditRun.action == "document.review", AuditRun.entity_id == document.id)
    ).all()
    assert len(audits) == 1
    assert audits[0].status == "error"
    assert audits[0].entity_type == "document"
    haystack = str(audits[0].error) + str(audits[0].input_json) + str(audits[0].output_json)
    for secret in ("sk-test-secret", "Authorization: Bearer secret", "raw-provider-body", DANGEROUS_ERROR_TEXT):
        assert secret not in haystack

    # No usable review could be stored: the recovery transaction still marks the
    # document `review_failed`.
    # The HTTP request committed through a separate request-scoped `Session`;
    # `expire_all()` forces this test session to re-read from the database
    # instead of returning its own stale cached `Document` instance.
    db_session.expire_all()
    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.review_failed.value


# ---------------------------------------------------------------------------
# H. Stateless AI success
# ---------------------------------------------------------------------------


def test_ai_review_success(client, db_session):
    final_review = _final_review(needs_review=False, reason_codes=[])
    fake = _FakeOrchestrator(result=_orchestration_result(final_review, used_fallback=False))
    app.dependency_overrides[get_review_orchestrator] = lambda: fake

    response = client.post("/api/ai/review", json={"title": "Заголовок", "text": NON_VAGUE_TEXT})

    assert response.status_code == 200
    body = response.json()
    assert fake.calls == [NON_VAGUE_TEXT]
    assert "id" not in body
    assert "document_id" not in body
    assert "created_at" not in body
    assert body["needs_review"] is False
    assert body["reason_codes"] == []
    assert body["error"] is None
    assert body["review_json"]["summary"] == final_review.summary

    assert db_session.scalar(select(func.count()).select_from(Document)) == 0
    assert db_session.scalar(select(func.count()).select_from(Review)) == 0

    audits = _ai_review_audits(db_session)
    assert len(audits) == 1
    assert audits[0].status == "success"
    assert audits[0].error is None
    assert audits[0].entity_type is None
    assert audits[0].entity_id is None
    assert audits[0].output_json["needs_review"] is False
    assert audits[0].output_json["review_reason_codes"] == []


def test_ai_review_text_passed_verbatim_after_trim(client, db_session):
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    app.dependency_overrides[get_review_orchestrator] = lambda: fake

    client.post("/api/ai/review", json={"text": f"  {NON_VAGUE_TEXT}  "})

    assert fake.calls == [NON_VAGUE_TEXT]


# ---------------------------------------------------------------------------
# I. Stateless AI fallback
# ---------------------------------------------------------------------------


def test_ai_review_fallback_returns_normal_response(client, db_session):
    fallback_review = build_fallback_review(
        original_text=NON_VAGUE_TEXT, root_reason_code=ReviewReasonCode.MODEL_ERROR
    )
    fake = _FakeOrchestrator(
        result=_orchestration_result(
            fallback_review, used_fallback=True, llm_error_category=LLMErrorCategory.TRANSPORT_ERROR
        )
    )
    app.dependency_overrides[get_review_orchestrator] = lambda: fake

    response = client.post("/api/ai/review", json={"text": NON_VAGUE_TEXT})

    assert response.status_code == 200
    body = response.json()
    assert body["needs_review"] is True
    assert "MODEL_ERROR" in body["reason_codes"]
    assert body["error"] is None

    assert db_session.scalar(select(func.count()).select_from(Document)) == 0
    assert db_session.scalar(select(func.count()).select_from(Review)) == 0

    audits = _ai_review_audits(db_session)
    assert len(audits) == 1
    assert audits[0].status == "error"
    assert audits[0].error
    # Business-facing error text never names the raw LLM error category — it
    # still lives on, separately, in `output_json.llm_error_category` below.
    assert "TRANSPORT_ERROR" not in audits[0].error
    assert audits[0].entity_type is None
    assert audits[0].entity_id is None
    assert audits[0].output_json["needs_review"] is True
    assert "MODEL_ERROR" in audits[0].output_json["review_reason_codes"]


# ---------------------------------------------------------------------------
# J. Request validation
# ---------------------------------------------------------------------------


def test_ai_review_blank_text_returns_422(client):
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    app.dependency_overrides[get_review_orchestrator] = lambda: fake

    response = client.post("/api/ai/review", json={"text": "   "})

    assert response.status_code == 422
    assert fake.calls == []


def test_ai_review_missing_text_returns_422(client):
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    app.dependency_overrides[get_review_orchestrator] = lambda: fake

    response = client.post("/api/ai/review", json={"title": "Only title"})

    assert response.status_code == 422
    assert fake.calls == []


def test_ai_review_blank_title_returns_422(client):
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    app.dependency_overrides[get_review_orchestrator] = lambda: fake

    response = client.post("/api/ai/review", json={"title": "   ", "text": NON_VAGUE_TEXT})

    assert response.status_code == 422
    assert fake.calls == []


def test_ai_review_extra_field_returns_422(client):
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    app.dependency_overrides[get_review_orchestrator] = lambda: fake

    response = client.post("/api/ai/review", json={"text": NON_VAGUE_TEXT, "content": "unexpected"})

    assert response.status_code == 422
    assert fake.calls == []


def test_ai_review_wrong_type_text_returns_422(client):
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    app.dependency_overrides[get_review_orchestrator] = lambda: fake

    response = client.post("/api/ai/review", json={"text": 12345})

    assert response.status_code == 422
    assert fake.calls == []


def test_ai_review_missing_body_returns_422(client):
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    app.dependency_overrides[get_review_orchestrator] = lambda: fake

    response = client.post("/api/ai/review", json={})

    assert response.status_code == 422
    assert fake.calls == []


def test_ai_review_validation_error_does_not_require_openai_api_key(client):
    """No dependency override at all: proves the 422 path never reaches the LLM client."""
    assert os.environ.get("OPENAI_API_KEY", "") == ""

    response = client.post("/api/ai/review", json={"text": ""})

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 8. Explicit title: null rejection (MINOR 1)
#
# `title` may be omitted entirely, but an explicit JSON `null` must be
# rejected: a caller that wants "no title" omits the key, it does not send
# `null`.
# ---------------------------------------------------------------------------


def test_ai_review_omitted_title_is_valid(client):
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    app.dependency_overrides[get_review_orchestrator] = lambda: fake

    response = client.post("/api/ai/review", json={"text": NON_VAGUE_TEXT})

    assert response.status_code == 200
    assert fake.calls == [NON_VAGUE_TEXT]


def test_ai_review_explicit_null_title_returns_422(client):
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    app.dependency_overrides[get_review_orchestrator] = lambda: fake

    response = client.post("/api/ai/review", json={"title": None, "text": NON_VAGUE_TEXT})

    assert response.status_code == 422
    assert fake.calls == []


def test_ai_review_whitespace_only_title_returns_422(client):
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    app.dependency_overrides[get_review_orchestrator] = lambda: fake

    response = client.post("/api/ai/review", json={"title": "   ", "text": NON_VAGUE_TEXT})

    assert response.status_code == 422
    assert fake.calls == []


def test_ai_review_title_is_trimmed_before_reaching_audit_metadata(client, db_session):
    """The orchestrator itself never receives `title` (only `text`); the trimmed
    value's effect is observable in the persisted audit snapshot's `title_length`."""
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    app.dependency_overrides[get_review_orchestrator] = lambda: fake

    response = client.post("/api/ai/review", json={"title": "  Название  ", "text": NON_VAGUE_TEXT})

    assert response.status_code == 200
    audits = _ai_review_audits(db_session)
    assert len(audits) == 1
    assert audits[0].input_json["title_length"] == len("Название")


def test_ai_review_title_not_nullable_in_openapi_schema(client):
    """The field stays omittable (not in `required`) but its declared schema
    is exactly `{"type": "string", ...}` — no `default`, no `anyOf`/`null` — so
    a generated client cannot read the schema as license to send `title: null`,
    even though the field may be left out entirely. Read from the real
    `GET /openapi.json` response (not `AIReviewRequest.model_json_schema()`
    called directly), so this also catches any FastAPI-side schema
    transformation, not just what Pydantic alone would produce."""
    schema = client.get("/openapi.json").json()
    request_schema = schema["components"]["schemas"]["AIReviewRequest"]
    assert "title" not in request_schema.get("required", [])

    title_schema = request_schema["properties"]["title"]
    assert title_schema.get("type") == "string"
    assert "default" not in title_schema
    assert "nullable" not in title_schema
    assert "anyOf" not in title_schema
    assert "oneOf" not in title_schema
    assert "null" not in json.dumps(title_schema)


def test_ai_review_request_model_json_schema_title_has_no_default_or_null():
    """Direct Pydantic-level check (independent of FastAPI's OpenAPI assembly):
    `AIReviewRequest.model_json_schema()` itself must already satisfy the
    contract, confirming the fix lives in the schema, not in some FastAPI-side
    post-processing step."""
    schema = AIReviewRequest.model_json_schema()
    assert "title" not in schema.get("required", [])
    title_schema = schema["properties"]["title"]
    assert title_schema == {"title": "Title", "type": "string"}


@pytest.mark.parametrize(
    "payload,expect_valid,expected_title",
    [
        pytest.param({"text": NON_VAGUE_TEXT}, True, None, id="omitted"),
        pytest.param({"title": None, "text": NON_VAGUE_TEXT}, False, None, id="explicit_null"),
        pytest.param({"title": "   ", "text": NON_VAGUE_TEXT}, False, None, id="blank"),
        pytest.param(
            {"title": "  Название  ", "text": NON_VAGUE_TEXT}, True, "Название", id="trimmed"
        ),
    ],
)
def test_ai_review_request_direct_pydantic_validation(payload, expect_valid, expected_title):
    """Direct `AIReviewRequest.model_validate(...)` check for the four runtime
    scenarios required by the contract, independent of the HTTP layer."""
    if expect_valid:
        request = AIReviewRequest.model_validate(payload)
        assert request.title == expected_title
    else:
        with pytest.raises(ValidationError):
            AIReviewRequest.model_validate(payload)


# ---------------------------------------------------------------------------
# 9. HTTPException passthrough — must not be swallowed into a generic 500
# (MINOR 2)
# ---------------------------------------------------------------------------


def test_document_review_httpexception_from_dependency_preserves_status(client):
    class _ConflictWorkflow:
        def run(self, document_id):
            raise HTTPException(status_code=409, detail="Конфликт состояния документа")

    app.dependency_overrides[get_review_workflow] = lambda: _ConflictWorkflow()

    response = client.post(f"/api/documents/{uuid.uuid4()}/review")

    assert response.status_code == 409
    assert response.json()["detail"] == "Конфликт состояния документа"


def test_document_review_document_not_found_still_returns_404_after_httpexception_fix(client):
    response = client.post(f"/api/documents/{uuid.uuid4()}/review")
    assert response.status_code == 404


def test_document_review_ordinary_error_still_returns_fixed_500_after_httpexception_fix(client, db_session):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    fake = _FakeOrchestrator(exception=RuntimeError("boom"))
    app.dependency_overrides[get_review_orchestrator] = lambda: fake

    response = client.post(f"/api/documents/{document.id}/review")

    assert response.status_code == 500
    assert response.json()["detail"] == "Не удалось выполнить проверку документа."


def test_ai_review_httpexception_from_dependency_preserves_status(client):
    class _ConflictService:
        def review(self, *, title, text):
            raise HTTPException(status_code=409, detail="Конфликт")

    app.dependency_overrides[get_ai_review_service] = lambda: _ConflictService()

    response = client.post("/api/ai/review", json={"text": NON_VAGUE_TEXT})

    assert response.status_code == 409
    assert response.json()["detail"] == "Конфликт"


def test_ai_review_ordinary_error_still_returns_fixed_500_after_httpexception_fix(client):
    fake = _FakeOrchestrator(exception=RuntimeError("boom"))
    app.dependency_overrides[get_review_orchestrator] = lambda: fake

    response = client.post("/api/ai/review", json={"text": NON_VAGUE_TEXT})

    assert response.status_code == 500
    assert response.json()["detail"] == "Не удалось выполнить проверку текста."


# ---------------------------------------------------------------------------
# 10. OpenAPI operation descriptions (MINOR 3)
# ---------------------------------------------------------------------------


def _looks_non_ascii(text: str) -> bool:
    return any(ord(ch) > 127 for ch in text)


def test_document_review_openapi_has_nonempty_russian_description(client):
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/api/documents/{document_id}/review"]["post"]
    description = operation.get("description")
    assert description
    assert _looks_non_ascii(description)


def test_ai_review_openapi_has_nonempty_russian_description(client):
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/api/ai/review"]["post"]
    description = operation.get("description")
    assert description
    assert _looks_non_ascii(description)


def test_document_review_openapi_description_distinguishes_fallback_from_manual_review(client):
    """Regression for the contract-reconciliation fix: the description previously
    called the persisted safe fallback "ручная проверка, а не ошибка" ("manual
    review, not an error"), contradicting its actual semantics
    (`AuditRun.status="error"`, `Document.status="review_failed"`). It must now
    state the technical-fallback semantics explicitly and keep them distinct from
    an ordinary `needs_review=true` result that is not a technical failure. Checked
    via a handful of key fragments rather than the full paragraph, so the test does
    not become brittle to unrelated wording changes."""
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/api/documents/{document_id}/review"]["post"]
    description = operation.get("description")
    assert description
    assert _looks_non_ascii(description)

    # The old, incorrect characterization of a technical fallback as "manual
    # review, not an error" must be gone.
    assert "ручная проверка, а не ошибка" not in description

    # Technical fallback: still 201, but a real technical error, safely contained.
    assert "техническая ошибка" in description
    assert "AuditRun.status=error" in description
    assert "Document.status=review_failed" in description
    assert "Review.error" in description

    # Ordinary needs_review=true (no technical fallback) is explicitly not an error.
    assert "не ошибка" in description
    assert "AuditRun.status=needs_review" in description
    assert "Document.status=reviewed" in description


def test_document_review_openapi_description_does_not_claim_category_in_business_error(client):
    """Regression for the documentation-reconciliation fix: the description
    previously implied `Review.error` is filled with "безопасным описанием
    категории сбоя" (a safe *description of the failure category*) — wrong,
    since the actual runtime `error` is one fixed, category-independent
    business message (`app/services/review_workflow.py::_FALLBACK_ERROR_MESSAGE`)
    and the real `LLMErrorCategory` value is never folded into it. The category
    is only ever recorded separately, as technical audit metadata
    (`AuditRun.output_json.llm_error_category`). Checked via key contract
    fragments, not the full paragraph, so this stays robust to unrelated
    wording changes."""
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/api/documents/{document_id}/review"]["post"]
    description = operation.get("description")
    assert description

    # The old, incorrect claim that Review.error holds a category description
    # must be gone.
    assert "описанием категории сбоя" not in description

    # The business error is documented as a fixed, safe, user-facing message.
    assert "фиксированным безопасным" in description
    assert "Review.error" in description

    # No specific failure-category enum value is ever presented as part of
    # what the business `Review.error` may contain.
    assert "API_ERROR" not in description
    assert "CONFIGURATION_ERROR" not in description
    assert "LLMErrorCategory" not in description

    # The technical metadata field where the category *does* live is named
    # explicitly — this is the desired, qualified reference.
    assert "AuditRun.output_json.llm_error_category" in description


# ---------------------------------------------------------------------------
# 11. Stateless ai.review audit snapshot (MAJOR 2)
#
# Unlike a persisted `Review` row, `audit_runs` is the *only* durable trace of
# a stateless `/api/ai/review` outcome, so its snapshot must carry enough to
# reconstruct what happened: prompt/schema version, the configured model,
# and — beyond the original `used_fallback`/`llm_error_category` — the final
# `needs_review` and ordered `review_reason_codes`, without ever storing the
# full submitted text or an exception message.
# ---------------------------------------------------------------------------


def test_ai_review_audit_snapshot_success(client, db_session):
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    app.dependency_overrides[get_review_orchestrator] = lambda: fake
    app.dependency_overrides[get_configured_model_name] = lambda: "gpt-test-model"

    response = client.post("/api/ai/review", json={"title": "Заголовок", "text": NON_VAGUE_TEXT})
    assert response.status_code == 200

    audits = _ai_review_audits(db_session)
    assert len(audits) == 1
    audit = audits[0]
    assert audit.status == "success"
    assert audit.error is None

    assert audit.input_json["prompt_version"] == PROMPT_VERSION
    assert audit.input_json["review_schema_version"] == REVIEW_SCHEMA_VERSION
    assert audit.input_json["model"] == "gpt-test-model"
    assert audit.input_json["title_length"] == len("Заголовок")
    assert audit.input_json["text_length"] == len(NON_VAGUE_TEXT)

    assert audit.output_json["used_fallback"] is False
    assert audit.output_json["llm_error_category"] is None
    assert audit.output_json["needs_review"] is False
    assert audit.output_json["review_reason_codes"] == []

    haystack = str(audit.input_json) + str(audit.output_json) + str(audit.error)
    assert NON_VAGUE_TEXT not in haystack
    assert "Заголовок" not in haystack


def test_ai_review_audit_snapshot_needs_review_without_fallback(client, db_session):
    final_review = _final_review(
        needs_review=True,
        reason_codes=[ReviewReasonCode.LOW_CONFIDENCE, ReviewReasonCode.CONTRADICTORY_INPUT],
    )
    fake = _FakeOrchestrator(result=_orchestration_result(final_review, used_fallback=False))
    app.dependency_overrides[get_review_orchestrator] = lambda: fake
    app.dependency_overrides[get_configured_model_name] = lambda: "gpt-test-model"

    response = client.post("/api/ai/review", json={"text": NON_VAGUE_TEXT})
    assert response.status_code == 200

    audits = _ai_review_audits(db_session)
    assert len(audits) == 1
    audit = audits[0]
    assert audit.status == "needs_review"
    assert audit.error is None
    assert audit.output_json["used_fallback"] is False
    assert audit.output_json["llm_error_category"] is None
    assert audit.output_json["needs_review"] is True
    # Catalogue order (REVIEW_SCHEMA.md): LOW_CONFIDENCE before CONTRADICTORY_INPUT.
    assert audit.output_json["review_reason_codes"] == ["LOW_CONFIDENCE", "CONTRADICTORY_INPUT"]


def test_ai_review_audit_snapshot_safe_fallback(client, db_session):
    fallback_review = build_fallback_review(
        original_text=NON_VAGUE_TEXT, root_reason_code=ReviewReasonCode.SCHEMA_MISMATCH
    )
    fake = _FakeOrchestrator(
        result=_orchestration_result(
            fallback_review, used_fallback=True, llm_error_category=LLMErrorCategory.SCHEMA_MISMATCH
        )
    )
    app.dependency_overrides[get_review_orchestrator] = lambda: fake
    app.dependency_overrides[get_configured_model_name] = lambda: "gpt-test-model"

    response = client.post("/api/ai/review", json={"text": NON_VAGUE_TEXT})
    assert response.status_code == 200
    body = response.json()
    assert body["needs_review"] is True

    audits = _ai_review_audits(db_session)
    assert len(audits) == 1
    audit = audits[0]
    assert audit.status == "error"
    assert audit.error
    # Business-facing error text never names the raw LLM error category — it
    # still lives on, separately, in `output_json.llm_error_category` below.
    assert "SCHEMA_MISMATCH" not in audit.error

    assert audit.input_json["model"] == "gpt-test-model"
    assert audit.input_json["prompt_version"] == PROMPT_VERSION
    assert audit.input_json["review_schema_version"] == REVIEW_SCHEMA_VERSION

    assert audit.output_json["used_fallback"] is True
    assert audit.output_json["llm_error_category"] == "SCHEMA_MISMATCH"
    assert audit.output_json["needs_review"] is True
    assert "SCHEMA_MISMATCH" in audit.output_json["review_reason_codes"]

    haystack = str(audit.input_json) + str(audit.output_json) + str(audit.error)
    assert NON_VAGUE_TEXT not in haystack
    assert "LLMClientError" not in haystack
    assert "Traceback" not in haystack


def test_ai_review_audit_snapshot_without_configured_model_stores_null(client, db_session):
    """No `get_configured_model_name` override: the test environment's
    `OPENAI_MODEL` is blank, so the snapshot must record `null`, not an empty
    string or a private OpenAI SDK client attribute."""
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    app.dependency_overrides[get_review_orchestrator] = lambda: fake

    response = client.post("/api/ai/review", json={"text": NON_VAGUE_TEXT})
    assert response.status_code == 200

    audits = _ai_review_audits(db_session)
    assert audits[0].input_json["model"] is None


# ---------------------------------------------------------------------------
# G'/7. AI review fatal error / recovery-audit contract (MAJOR 1)
#
# Unlike `ReviewWorkflow` (which has an existing `document`/`review` row to
# attach an error audit to), `AIReviewService` never creates a `Document` or
# `Review`, so its *only* durable trace of a fatal failure is the recovery
# `ai.review` AuditRun written here. A fatal orchestrator/audit failure must
# therefore still leave exactly one `ai.review` error-audit row behind, never
# zero (nothing is auditable) and never two (duplicate audit).
# ---------------------------------------------------------------------------


def test_ai_review_fatal_error_returns_500_and_writes_exactly_one_error_audit(client, db_session):
    """Section 7.A: orchestrator RuntimeError with dangerous markers."""
    fake = _FakeOrchestrator(exception=RuntimeError(DANGEROUS_ERROR_TEXT))
    app.dependency_overrides[get_review_orchestrator] = lambda: fake

    response = client.post("/api/ai/review", json={"text": NON_VAGUE_TEXT})

    assert response.status_code == 500
    raw_body = response.text
    for secret in ("sk-test-secret", "Authorization: Bearer secret", "raw-provider-body", DANGEROUS_ERROR_TEXT):
        assert secret not in raw_body

    assert db_session.scalar(select(func.count()).select_from(Document)) == 0
    assert db_session.scalar(select(func.count()).select_from(Review)) == 0

    audits = _ai_review_audits(db_session)
    assert len(audits) == 1
    audit = audits[0]
    assert audit.status == "error"
    assert audit.error
    assert audit.error == ai_review_service_module._UNEXPECTED_ERROR_AUDIT_MESSAGE
    assert audit.entity_type is None
    assert audit.entity_id is None
    assert audit.output_json is None

    haystack = str(audit.error) + str(audit.input_json) + str(audit.output_json)
    for secret in ("sk-test-secret", "Authorization: Bearer secret", "raw-provider-body", DANGEROUS_ERROR_TEXT):
        assert secret not in haystack


def test_ai_review_service_no_open_transaction_during_orchestrator_call(db_session):
    """Section 6: the orchestrator call itself runs with no open transaction."""
    tracking = _TrackingOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False),
        session=db_session,
    )
    service = AIReviewService(session=db_session, orchestrator=tracking, model_name="gpt-test-model")

    service.review(title=None, text=NON_VAGUE_TEXT)

    assert tracking.in_transaction_snapshots == [False]
    assert db_session.in_transaction() is False


def test_ai_review_service_ordinary_audit_failure_triggers_recovery_audit_and_reraises(db_session, monkeypatch):
    """Section 7.B: the *ordinary* success/fallback audit commit fails for real.

    Tested directly against `AIReviewService` (not through HTTP), like the
    equivalent `ReviewWorkflow` tests in `tests/test_review_workflow.py`: the
    session-state invariants under test (`in_transaction()`/`is_active` and a
    follow-up `SELECT`) describe the request-scoped session's contract, which a
    closed post-request `TestClient` session can no longer be inspected for.
    """
    fake = _FakeOrchestrator(
        result=_orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)
    )
    service = AIReviewService(session=db_session, orchestrator=fake, model_name="gpt-test-model")

    original_record = AuditService.record
    call_count = {"n": 0}

    def _flaky_record(self, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("forced audit insert failure")
        return original_record(self, **kwargs)

    monkeypatch.setattr(AuditService, "record", _flaky_record)

    with pytest.raises(RuntimeError, match="forced audit insert failure"):
        service.review(title=None, text=NON_VAGUE_TEXT)

    assert db_session.in_transaction() is False
    assert db_session.is_active is True
    assert db_session.scalar(select(func.count()).select_from(Document)) == 0  # a plain SELECT still works

    audits = db_session.scalars(select(AuditRun).where(AuditRun.action == "ai.review")).all()
    assert len(audits) == 1
    assert audits[0].status == "error"
    assert audits[0].error == ai_review_service_module._UNEXPECTED_ERROR_AUDIT_MESSAGE
    assert audits[0].entity_type is None
    assert audits[0].entity_id is None


def test_ai_review_service_recovery_audit_failure_does_not_replace_original_exception(db_session, monkeypatch):
    """Section 7.C: the *recovery* audit write itself fails with a real
    `IntegrityError` (the `ck_audit_runs_status` CHECK constraint), not merely a
    monkeypatched exception — mirrors
    `test_review_workflow.py::test_real_error_audit_flush_failure_does_not_replace_original_exception`.
    """
    fake = _FakeOrchestrator(exception=RuntimeError("primary ai review failure"))
    service = AIReviewService(session=db_session, orchestrator=fake, model_name="gpt-test-model")

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

    with pytest.raises(RuntimeError, match="primary ai review failure"):
        service.review(title=None, text=NON_VAGUE_TEXT)

    assert db_session.in_transaction() is False
    assert db_session.is_active is True
    assert db_session.scalar(select(func.count()).select_from(AuditRun)) == 0  # no partial row
    assert db_session.scalar(select(func.count()).select_from(Document)) == 0  # a plain SELECT still works


@pytest.mark.parametrize("exc_type", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_ai_review_service_base_exception_propagates_without_recovery_audit(db_session, exc_type):
    """Section 7.D: BaseException subclasses are never caught, so no recovery
    audit is written for them, and they propagate unchanged."""
    fake = _FakeOrchestrator(exception=exc_type())
    service = AIReviewService(session=db_session, orchestrator=fake, model_name="gpt-test-model")

    with pytest.raises(exc_type):
        service.review(title=None, text=NON_VAGUE_TEXT)

    assert db_session.in_transaction() is False
    assert db_session.scalar(select(func.count()).select_from(AuditRun)) == 0


# ---------------------------------------------------------------------------
# K. No API key at import / health
# ---------------------------------------------------------------------------


def test_app_imports_and_health_works_without_openai_api_key(client):
    assert os.environ.get("OPENAI_API_KEY", "") == ""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# L. OpenAPI safety
# ---------------------------------------------------------------------------


def test_openapi_schema_does_not_leak_sensitive_fields(client):
    raw_schema = client.get("/openapi.json").text
    for marker in (
        "api_key",
        "OPENAI_API_KEY",
        "Authorization",
        "sk-",
        "traceback",
    ):
        assert marker not in raw_schema


# ---------------------------------------------------------------------------
# M. Real dependency-graph wiring (no fully mocked router)
# ---------------------------------------------------------------------------


def test_document_review_wiring_through_real_orchestrator_and_workflow(client, db_session):
    document = make_document(db_session, text=NON_VAGUE_TEXT)
    draft = ModelReviewDraft(**VALID_DRAFT_KWARGS)
    fake_llm_client = _FakeLLMClient(draft=draft)
    app.dependency_overrides[get_review_client] = lambda: fake_llm_client

    response = client.post(f"/api/documents/{document.id}/review")

    assert response.status_code == 201
    assert fake_llm_client.calls == [document.text]
    body = response.json()

    stored_review = db_session.get(Review, body["id"])
    assert stored_review is not None
    assert stored_review.document_id == document.id
    assert stored_review.review_json["summary"] == draft.summary

    # The HTTP request committed through a separate request-scoped `Session`;
    # `expire_all()` forces this test session to re-read from the database
    # instead of returning its own stale cached `Document` instance.
    db_session.expire_all()
    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.reviewed.value

    audit = _document_review_audit(db_session, body["id"])
    assert audit.status == "success"


def test_document_review_wiring_llm_failure_persists_safe_fallback(client, db_session):
    document = make_document(db_session, text=NON_VAGUE_TEXT)

    fake_llm_client = _FakeLLMClient(exception=LLMTransportError("Не удалось установить соединение."))
    app.dependency_overrides[get_review_client] = lambda: fake_llm_client

    response = client.post(f"/api/documents/{document.id}/review")

    assert response.status_code == 201
    body = response.json()
    assert body["needs_review"] is True
    assert "MODEL_ERROR" in body["reason_codes"]
    assert body["error"]

    stored_review = db_session.get(Review, body["id"])
    assert stored_review is not None
    assert stored_review.error

    audit = _document_review_audit(db_session, body["id"])
    assert audit.status == "error"
    assert audit.error

    # The HTTP request committed through a separate request-scoped `Session`;
    # `expire_all()` forces this test session to re-read from the database
    # instead of returning its own stale cached `Document` instance.
    db_session.expire_all()
    stored_document = db_session.get(Document, document.id)
    assert stored_document.status == DocumentStatus.review_failed.value


def test_ai_review_wiring_through_real_orchestrator(client, db_session):
    draft = ModelReviewDraft(**VALID_DRAFT_KWARGS)
    fake_llm_client = _FakeLLMClient(draft=draft)
    app.dependency_overrides[get_review_client] = lambda: fake_llm_client

    response = client.post("/api/ai/review", json={"title": "T", "text": NON_VAGUE_TEXT})

    assert response.status_code == 200
    assert fake_llm_client.calls == [NON_VAGUE_TEXT]
    body = response.json()
    assert body["review_json"]["summary"] == draft.summary
    assert body["needs_review"] is False

    assert db_session.scalar(select(func.count()).select_from(Document)) == 0
    assert db_session.scalar(select(func.count()).select_from(Review)) == 0

    audits = _ai_review_audits(db_session)
    assert len(audits) == 1
    assert audits[0].status == "success"


def test_ai_review_service_dependency_override_bypasses_orchestrator_entirely(client, db_session):
    """Confirms `get_ai_review_service` is independently overridable, as required
    for tests that want to fake the whole service rather than just the LLM client
    or the orchestrator."""

    class _FakeAIReviewService:
        def __init__(self) -> None:
            self.calls: List[tuple] = []

        def review(self, *, title, text):
            self.calls.append((title, text))
            return _orchestration_result(_final_review(needs_review=False, reason_codes=[]), used_fallback=False)

    fake_service = _FakeAIReviewService()
    app.dependency_overrides[get_ai_review_service] = lambda: fake_service

    response = client.post("/api/ai/review", json={"text": NON_VAGUE_TEXT})

    assert response.status_code == 200
    assert fake_service.calls == [(None, NON_VAGUE_TEXT)]
    assert db_session.scalar(select(func.count()).select_from(AuditRun)) == 0

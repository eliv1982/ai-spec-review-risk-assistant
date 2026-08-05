from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, inspect, select
from sqlalchemy.exc import StatementError

import app.database as database_module
from app.database import engine
from app.models import AuditRun, Document, Review
from app.repositories.review_repository import ReviewRepository
from app.utils.json_type import NonFiniteJSONValueError
from tests.helpers import make_audit_run, make_document, make_review


def test_exactly_three_application_tables_exist():
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    assert table_names == {"documents", "reviews", "audit_runs"}


def test_sqlite_foreign_key_enforcement_is_enabled():
    with engine.connect() as connection:
        result = connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
    assert result == 1


def test_deleting_document_cascades_to_reviews(db_session):
    document = make_document(db_session)
    review = make_review(db_session, document_id=document.id)
    document_id, review_id = document.id, review.id

    db_session.execute(delete(Document).where(Document.id == document_id))
    db_session.commit()

    remaining_id = db_session.execute(
        select(Review.id).where(Review.id == review_id)
    ).scalar_one_or_none()
    assert remaining_id is None


def test_deleting_document_does_not_delete_audit_rows(db_session):
    document = make_document(db_session)
    document_id = document.id
    audit_run = make_audit_run(
        db_session,
        action="document.create",
        status="success",
        entity_type="document",
        entity_id=document_id,
    )
    audit_run_id = audit_run.id

    db_session.execute(delete(Document).where(Document.id == document_id))
    db_session.commit()

    remaining_audit = db_session.get(AuditRun, audit_run_id)
    assert remaining_audit is not None
    assert remaining_audit.entity_id == document_id

    remaining_document = db_session.get(Document, document_id)
    assert remaining_document is None


def test_json_fields_round_trip(db_session):
    document = make_document(db_session)
    original_review_json = {
        "summary": "s",
        "nested": {"a": [1, 2, {"b": None}], "flag": True},
        "risks": [],
        "missing_requirements": [],
        "contradictions": [],
        "questions_to_client": [],
        "acceptance_criteria": [],
        "confidence": "low",
        "document_readiness": "not_ready",
        "needs_review": True,
        "review_reason_codes": ["LOW_CONFIDENCE", "TOO_VAGUE_INPUT"],
    }
    review = make_review(
        db_session,
        document_id=document.id,
        review_json=original_review_json,
        reason_codes=["LOW_CONFIDENCE", "TOO_VAGUE_INPUT"],
    )

    db_session.expire_all()
    reloaded = db_session.get(Review, review.id)

    assert reloaded.review_json == original_review_json
    assert isinstance(reloaded.review_json, dict)
    assert reloaded.reason_codes_json == ["LOW_CONFIDENCE", "TOO_VAGUE_INPUT"]
    assert isinstance(reloaded.reason_codes_json, list)

    audit_run = make_audit_run(
        db_session,
        input_json={"a": 1, "b": [1, 2, 3]},
        output_json={"ok": True},
    )
    db_session.expire_all()
    reloaded_audit = db_session.get(AuditRun, audit_run.id)
    assert reloaded_audit.input_json == {"a": 1, "b": [1, 2, 3]}
    assert reloaded_audit.output_json == {"ok": True}


def test_review_fixture_denormalized_fields_match_review_json(db_session):
    document = make_document(db_session)
    review = make_review(
        db_session,
        document_id=document.id,
        confidence="high",
        readiness="ready",
        needs_review=False,
        reason_codes=[],
    )

    assert review.review_json["confidence"] == review.confidence == "high"
    assert review.review_json["document_readiness"] == review.readiness == "ready"
    assert review.review_json["needs_review"] is False
    assert bool(review.needs_review) is False
    assert review.review_json["review_reason_codes"] == review.reason_codes_json == []


def test_persisting_non_finite_float_in_review_json_raises(db_session):
    document = make_document(db_session)
    repo = ReviewRepository(db_session)
    repo.add(
        document_id=document.id,
        review_json={"summary": "s", "score": float("nan")},
        confidence="low",
        readiness="not_ready",
        needs_review=True,
        reason_codes=["LOW_CONFIDENCE"],
    )

    # SQLAlchemy wraps the bind-param processing error raised by JSONText in a
    # StatementError; the original, clear exception is preserved as `.orig`.
    with pytest.raises(StatementError) as exc_info:
        db_session.flush()
    assert isinstance(exc_info.value.orig, NonFiniteJSONValueError)
    db_session.rollback()


def test_creating_engine_does_not_create_sqlite_directory(tmp_path):
    target_dir = tmp_path / "not_yet_created"
    database_url = f"sqlite:///{target_dir}/isolated.db"

    fresh_engine = database_module.create_db_engine(database_url)
    try:
        assert not target_dir.exists()
    finally:
        fresh_engine.dispose()


def test_init_db_creates_the_sqlite_directory_on_deliberate_startup(tmp_path, monkeypatch):
    target_dir = tmp_path / "created_on_init"
    database_url = f"sqlite:///{target_dir}/isolated.db"
    fresh_engine = database_module.create_db_engine(database_url)
    assert not target_dir.exists()

    monkeypatch.setattr(database_module, "engine", fresh_engine)
    monkeypatch.setattr(database_module.settings, "database_url", database_url)

    try:
        database_module.init_db()
        assert target_dir.exists()
        assert (target_dir / "isolated.db").exists()
    finally:
        fresh_engine.dispose()


def test_timestamps_end_in_z(db_session):
    document = make_document(db_session)
    review = make_review(db_session, document_id=document.id)
    audit_run = make_audit_run(db_session, entity_id=document.id)

    for value in (document.created_at, review.created_at, audit_run.created_at):
        assert value.endswith("Z")
        # Must parse as a valid UTC ISO 8601 timestamp.
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == timezone.utc.utcoffset(parsed)

import csv
import io
import json
import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.repositories.review_repository import ReviewRepository
from app.services.display_labels import format_datetime_ru, label_reason_code
from tests.helpers import audit_run_snapshot, make_audit_run, make_document, make_review


def _ordering_key(item: dict) -> tuple[str, str]:
    return (item["created_at"], item["id"])


def _parse_csv(content: bytes) -> list[list[str]]:
    text = content.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text), delimiter=";"))


def test_list_reviews_empty(client):
    response = client.get("/api/reviews")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_review_json_and_reason_codes_are_native_json(client, db_session):
    document = make_document(db_session)
    make_review(
        db_session,
        document_id=document.id,
        review_json={"summary": "s", "nested": {"a": [1, 2, 3]}, "flag": True, "confidence": "low",
                      "document_readiness": "not_ready", "needs_review": True, "review_reason_codes": ["LOW_CONFIDENCE"],
                      "risks": [], "missing_requirements": [], "contradictions": [],
                      "questions_to_client": [], "acceptance_criteria": []},
        reason_codes=["LOW_CONFIDENCE", "MISSING_ACCEPTANCE_CRITERIA"],
    )

    response = client.get("/api/reviews")
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert isinstance(item["review_json"], dict)
    assert item["review_json"]["nested"] == {"a": [1, 2, 3]}
    assert item["review_json"]["flag"] is True
    assert isinstance(item["reason_codes"], list)
    assert item["reason_codes"] == ["LOW_CONFIDENCE", "MISSING_ACCEPTANCE_CRITERIA"]
    # review_json's own reason codes must be kept consistent with the reason_codes column.
    assert item["review_json"]["review_reason_codes"] == ["LOW_CONFIDENCE", "MISSING_ACCEPTANCE_CRITERIA"]
    assert "reason_codes_json" not in item


def test_get_review_by_id(client, db_session):
    document = make_document(db_session)
    review = make_review(db_session, document_id=document.id)

    response = client.get(f"/api/reviews/{review.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == review.id
    assert body["document_id"] == document.id
    assert body["needs_review"] is True
    assert body["reason_codes"] == ["LOW_CONFIDENCE"]
    assert body["error"] is None


def test_get_review_unknown_uuid_returns_404(client):
    response = client.get(f"/api/reviews/{uuid.uuid4()}")
    assert response.status_code == 404


def test_get_review_invalid_uuid_returns_422(client):
    response = client.get("/api/reviews/not-a-uuid")
    assert response.status_code == 422


def test_list_reviews_document_id_filter(client, db_session):
    doc_a = make_document(db_session, title="A", text="Text A")
    doc_b = make_document(db_session, title="B", text="Text B")
    review_a = make_review(db_session, document_id=doc_a.id)
    make_review(db_session, document_id=doc_b.id)

    response = client.get("/api/reviews", params={"document_id": doc_a.id})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == review_a.id


def test_list_reviews_document_id_invalid_uuid_returns_422(client):
    response = client.get("/api/reviews", params={"document_id": "not-a-uuid"})
    assert response.status_code == 422


def test_list_reviews_needs_review_filter(client, db_session):
    document = make_document(db_session)
    needs_true = make_review(db_session, document_id=document.id, needs_review=True)
    make_review(db_session, document_id=document.id, needs_review=False, reason_codes=[])

    response = client.get("/api/reviews", params={"needs_review": "true"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == needs_true.id


def test_list_reviews_confidence_and_readiness_filter(client, db_session):
    document = make_document(db_session)
    high_ready = make_review(
        db_session,
        document_id=document.id,
        confidence="high",
        readiness="ready",
        needs_review=False,
        reason_codes=[],
    )
    make_review(db_session, document_id=document.id, confidence="low", readiness="not_ready")

    # The fixture's denormalized columns must match its own review_json, the
    # same way a real FinalReview-derived row would.
    assert high_ready.review_json["confidence"] == "high"
    assert high_ready.review_json["document_readiness"] == "ready"
    assert high_ready.review_json["needs_review"] is False
    assert high_ready.review_json["review_reason_codes"] == []

    response = client.get("/api/reviews", params={"confidence": "high", "readiness": "ready"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == high_ready.id


def test_list_reviews_invalid_confidence_returns_422(client):
    response = client.get("/api/reviews", params={"confidence": "bogus"})
    assert response.status_code == 422


def test_list_reviews_deterministic_ordering(client, db_session):
    document = make_document(db_session)
    for _ in range(5):
        make_review(db_session, document_id=document.id)

    response = client.get("/api/reviews", params={"limit": 100})
    items = response.json()["items"]
    assert len(items) == 5
    keys = [_ordering_key(item) for item in items]
    assert keys == sorted(keys, reverse=True)


def test_list_reviews_pagination(client, db_session):
    document = make_document(db_session)
    for _ in range(5):
        make_review(db_session, document_id=document.id)

    first_page = client.get("/api/reviews", params={"limit": 2, "offset": 0}).json()
    second_page = client.get("/api/reviews", params={"limit": 2, "offset": 2}).json()

    assert len(first_page["items"]) == 2
    assert len(second_page["items"]) == 2
    assert first_page["total"] == 5
    first_ids = {item["id"] for item in first_page["items"]}
    second_ids = {item["id"] for item in second_page["items"]}
    assert first_ids.isdisjoint(second_ids)


def test_list_reviews_pagination_out_of_range_returns_422(client):
    assert client.get("/api/reviews", params={"limit": 0}).status_code == 422
    assert client.get("/api/reviews", params={"limit": 101}).status_code == 422
    assert client.get("/api/reviews", params={"offset": -1}).status_code == 422


# -----------------------------------------------------------------------------
# GET /api/reviews/export
# -----------------------------------------------------------------------------


def test_export_reviews_static_route_not_shadowed_by_uuid_detail_route(client):
    """REGRESSION: `/reviews/export` must hit the dedicated export handler, not
    the `/{review_id}` detail route with review_id="export" (which would fail
    UUID parsing with 422). Route registration order in app/api/reviews.py is
    what guarantees this."""
    response = client.get("/api/reviews/export")
    assert response.status_code == 200
    assert response.status_code != 422
    assert response.headers["content-type"].startswith("text/csv")


def test_export_reviews_empty_has_bom_and_header_only(client):
    response = client.get("/api/reviews/export")
    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    rows = _parse_csv(response.content)
    assert rows == [
        [
            "ID проверки",
            "ID документа",
            "Название документа",
            "Дата проверки",
            "Нужна экспертная проверка",
            "Уверенность анализа",
            "Статус готовности",
            "Причины экспертной проверки",
            "Ошибка",
        ]
    ]


def test_export_reviews_content_type_and_content_disposition(client):
    response = client.get("/api/reviews/export")
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="reviews-export.csv"'


def test_export_reviews_normal_row_and_russian_text(client, db_session):
    document = make_document(db_session, title="Договор на разработку ПО", text="Текст")
    review = make_review(
        db_session,
        document_id=document.id,
        confidence="high",
        readiness="ready",
        needs_review=False,
        reason_codes=[],
    )

    response = client.get("/api/reviews/export")
    rows = _parse_csv(response.content)
    assert len(rows) == 2
    data_row = rows[1]
    assert data_row[0] == review.id
    assert data_row[1] == document.id
    assert data_row[2] == "Договор на разработку ПО"
    assert data_row[3] == format_datetime_ru(review.created_at)
    assert data_row[4] == "Нет"
    assert data_row[5] == "Высокая"
    assert data_row[6] == "Готов"
    assert data_row[7] == ""
    assert data_row[8] == ""


def test_export_reviews_needs_review_true_and_reason_codes(client, db_session):
    document = make_document(db_session)
    review = make_review(
        db_session,
        document_id=document.id,
        needs_review=True,
        reason_codes=["LOW_CONFIDENCE", "MISSING_ACCEPTANCE_CRITERIA"],
    )

    response = client.get("/api/reviews/export")
    rows = _parse_csv(response.content)
    data_row = rows[1]
    assert data_row[0] == review.id
    assert data_row[4] == "Да"
    assert data_row[7] == (
        f"{label_reason_code('LOW_CONFIDENCE')}|{label_reason_code('MISSING_ACCEPTANCE_CRITERIA')}"
    )


def test_export_reviews_error_field(client, db_session):
    document = make_document(db_session)
    review = make_review(db_session, document_id=document.id, error="Сбой модели (сведения скрыты)")

    response = client.get("/api/reviews/export")
    rows = _parse_csv(response.content)
    data_row = rows[1]
    assert data_row[0] == review.id
    assert data_row[8] == "Сбой модели (сведения скрыты)"


def test_export_reviews_document_id_filter(client, db_session):
    doc_a = make_document(db_session, title="A", text="Text A")
    doc_b = make_document(db_session, title="B", text="Text B")
    review_a = make_review(db_session, document_id=doc_a.id)
    make_review(db_session, document_id=doc_b.id)

    response = client.get("/api/reviews/export", params={"document_id": doc_a.id})
    rows = _parse_csv(response.content)
    assert len(rows) == 2
    assert rows[1][0] == review_a.id


def test_export_reviews_needs_review_filter_true(client, db_session):
    document = make_document(db_session)
    needs_true = make_review(db_session, document_id=document.id, needs_review=True)
    make_review(db_session, document_id=document.id, needs_review=False, reason_codes=[])

    response = client.get("/api/reviews/export", params={"needs_review": "true"})
    rows = _parse_csv(response.content)
    assert len(rows) == 2
    assert rows[1][0] == needs_true.id


def test_export_reviews_needs_review_filter_false(client, db_session):
    document = make_document(db_session)
    make_review(db_session, document_id=document.id, needs_review=True)
    needs_false = make_review(db_session, document_id=document.id, needs_review=False, reason_codes=[])

    response = client.get("/api/reviews/export", params={"needs_review": "false"})
    rows = _parse_csv(response.content)
    assert len(rows) == 2
    assert rows[1][0] == needs_false.id


def test_export_reviews_confidence_and_readiness_filter(client, db_session):
    document = make_document(db_session)
    high_ready = make_review(
        db_session,
        document_id=document.id,
        confidence="high",
        readiness="ready",
        needs_review=False,
        reason_codes=[],
    )
    make_review(db_session, document_id=document.id, confidence="low", readiness="not_ready")

    response = client.get("/api/reviews/export", params={"confidence": "high", "readiness": "ready"})
    rows = _parse_csv(response.content)
    assert len(rows) == 2
    assert rows[1][0] == high_ready.id


def test_export_reviews_ignores_pagination_and_exports_all_matching_rows(client, db_session):
    document = make_document(db_session)
    for _ in range(120):
        make_review(db_session, document_id=document.id)

    # limit/offset are not accepted parameters of the export endpoint — even
    # if supplied, the export must return every matching row, well beyond the
    # list endpoint's own limit=100 cap.
    response = client.get("/api/reviews/export", params={"limit": 10, "offset": 0})
    rows = _parse_csv(response.content)
    assert len(rows) - 1 == 120


def test_export_reviews_stable_order_matches_list_endpoint(client, db_session):
    document = make_document(db_session)
    for _ in range(5):
        make_review(db_session, document_id=document.id)

    list_response = client.get("/api/reviews", params={"limit": 100})
    list_ids = [item["id"] for item in list_response.json()["items"]]

    export_response = client.get("/api/reviews/export")
    rows = _parse_csv(export_response.content)
    export_ids = [row[0] for row in rows[1:]]

    assert export_ids == list_ids


def test_export_reviews_safe_formula_escaping(client, db_session):
    document = make_document(db_session, title="=SUM(A1:A10)", text="Текст")
    review = make_review(db_session, document_id=document.id, error="+cmd|calc")

    response = client.get("/api/reviews/export")
    rows = _parse_csv(response.content)
    data_row = rows[1]
    assert data_row[0] == review.id
    assert data_row[2] == "'=SUM(A1:A10)"
    assert data_row[8] == "'+cmd|calc"


def test_export_reviews_does_not_create_audit_run(client, db_session):
    """CSV export is a read-only `GET` — it must never itself be recorded as
    an AuditRun row (it is not part of the audited write/action contract),
    and it must not mutate an already-existing audit row either. A plain
    `total` comparison would miss an in-place mutation (e.g. a row silently
    rewritten from status="success" to status="error") since row count alone
    is unchanged by that — the full snapshot comparison below catches it."""
    document = make_document(db_session)
    make_review(db_session, document_id=document.id)
    make_audit_run(db_session, action="document.create", status="success")
    before_total = client.get("/api/audit-runs", params={"limit": 100}).json()["total"]
    before_snapshot = audit_run_snapshot(db_session)

    response = client.get("/api/reviews/export")
    assert response.status_code == 200

    after_total = client.get("/api/audit-runs", params={"limit": 100}).json()["total"]
    assert after_total == before_total
    assert audit_run_snapshot(db_session) == before_snapshot


def test_export_reviews_read_failure_does_not_create_or_mutate_audit_run(db_session, monkeypatch):
    """A forced failure inside the real export read call path
    (`ReviewRepository.list_all_for_export`, the method `export_reviews`
    actually calls) must surface as the app's normal unhandled-error
    response, never as a written or mutated `audit_runs` row — CSV export
    failures are not audit events."""
    document = make_document(db_session)
    make_review(db_session, document_id=document.id)
    make_audit_run(db_session, action="document.create", status="success")
    before_snapshot = audit_run_snapshot(db_session)

    def _boom(self, **kwargs):
        raise RuntimeError("forced read failure for test")

    monkeypatch.setattr(ReviewRepository, "list_all_for_export", _boom)

    # Starlette's ServerErrorMiddleware re-raises the original exception after
    # sending our custom 500 response, so the default `client` fixture (which
    # asserts on that re-raise for debugging) would surface it as a test
    # failure instead of a response. raise_server_exceptions=False lets us
    # inspect the actual HTTP response the real client would receive —
    # mirrors test_documents.py::test_create_document_rolls_back_when_audit_persistence_fails.
    with TestClient(app, raise_server_exceptions=False) as local_client:
        response = local_client.get("/api/reviews/export")

    assert response.status_code == 500
    assert response.json() == {"detail": "Внутренняя ошибка сервера"}
    assert audit_run_snapshot(db_session) == before_snapshot


def test_export_reviews_document_title_uses_eager_loading_not_per_row_query(client, db_session):
    """REGRESSION: `ReviewRepository.list_all_for_export` must eager-load
    `Review.document` via a single JOIN (`joinedload`) — the document title
    column must not be fetched with a separate query per review row (N+1).
    This intentionally counts only statements that touch the `documents`
    table (a stable signal), not the exact total query count."""
    from sqlalchemy import event

    from app.database import engine

    for i in range(10):
        document = make_document(db_session, title=f"Документ {i}", text="Текст")
        make_review(db_session, document_id=document.id)

    statements: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _capture)
    try:
        response = client.get("/api/reviews/export")
    finally:
        event.remove(engine, "before_cursor_execute", _capture)

    assert response.status_code == 200
    document_touching_selects = [
        statement
        for statement in statements
        if "documents" in statement.lower() and statement.strip().upper().startswith("SELECT")
    ]
    assert len(document_touching_selects) <= 1, document_touching_selects


# -----------------------------------------------------------------------------
# GET /api/reviews/{review_id}/export
# -----------------------------------------------------------------------------


def test_export_review_success(client, db_session):
    document = make_document(db_session, title="Спецификация API", text="Текст")
    review = make_review(
        db_session,
        document_id=document.id,
        confidence="low",
        readiness="not_ready",
        needs_review=True,
        reason_codes=["LOW_CONFIDENCE"],
    )

    response = client.get(f"/api/reviews/{review.id}/export")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == f'attachment; filename="review-{review.id}.csv"'
    assert response.content.startswith(b"\xef\xbb\xbf")

    rows = _parse_csv(response.content)
    fields = {row[0]: row[1] for row in rows[1:]}
    assert rows[0] == ["Поле", "Значение"]
    assert fields["ID проверки"] == review.id
    assert fields["ID документа"] == document.id
    assert fields["Название документа"] == "Спецификация API"
    assert fields["Дата проверки"] == format_datetime_ru(review.created_at)
    assert fields["Нужна экспертная проверка"] == "Да"
    assert fields["Уверенность анализа"] == "Низкая"
    assert fields["Статус готовности"] == "Не готов"
    assert fields["Причины экспертной проверки"] == label_reason_code("LOW_CONFIDENCE")
    assert fields["Ошибка"] == ""
    assert json.loads(fields["Полный результат JSON"]) == review.review_json


def test_export_review_not_found_returns_404(client):
    response = client.get(f"/api/reviews/{uuid.uuid4()}/export")
    assert response.status_code == 404


def test_export_review_malformed_uuid_returns_422(client):
    response = client.get("/api/reviews/not-a-uuid/export")
    assert response.status_code == 422


def test_export_review_complete_json_cell_preserves_all_data(client, db_session):
    document = make_document(db_session)
    review_json = {
        "summary": "Резюме",
        "risks": [{"severity": "high", "category": "security", "description": "d", "evidence": None}],
        "missing_requirements": [],
        "contradictions": [],
        "questions_to_client": ["Вопрос?"],
        "acceptance_criteria": [],
        "confidence": "low",
        "document_readiness": "not_ready",
        "needs_review": True,
        "review_reason_codes": ["LOW_CONFIDENCE"],
    }
    review = make_review(db_session, document_id=document.id, review_json=review_json)

    response = client.get(f"/api/reviews/{review.id}/export")
    rows = _parse_csv(response.content)
    fields = {row[0]: row[1] for row in rows[1:]}
    assert json.loads(fields["Полный результат JSON"]) == review.review_json


def test_export_review_safe_error_text_escaping(client, db_session):
    document = make_document(db_session)
    review = make_review(db_session, document_id=document.id, error="=cmd|'/C calc'!A1")

    response = client.get(f"/api/reviews/{review.id}/export")
    rows = _parse_csv(response.content)
    fields = {row[0]: row[1] for row in rows[1:]}
    assert fields["Ошибка"] == "'=cmd|'/C calc'!A1"


def test_export_review_document_title_included(client, db_session):
    document = make_document(db_session, title="Название для CSV")
    review = make_review(db_session, document_id=document.id)

    response = client.get(f"/api/reviews/{review.id}/export")
    rows = _parse_csv(response.content)
    fields = {row[0]: row[1] for row in rows[1:]}
    assert fields["Название документа"] == "Название для CSV"


def test_export_review_does_not_create_audit_run(client, db_session):
    """CSV export is a read-only `GET` — it must never itself be recorded as
    an AuditRun row (it is not part of the audited write/action contract),
    and it must not mutate an already-existing audit row either. A plain
    `total` comparison would miss an in-place mutation (e.g. a row silently
    rewritten from status="success" to status="error") since row count alone
    is unchanged by that — the full snapshot comparison below catches it."""
    document = make_document(db_session)
    review = make_review(db_session, document_id=document.id)
    make_audit_run(db_session, action="document.create", status="success")
    before_total = client.get("/api/audit-runs", params={"limit": 100}).json()["total"]
    before_snapshot = audit_run_snapshot(db_session)

    response = client.get(f"/api/reviews/{review.id}/export")
    assert response.status_code == 200

    after_total = client.get("/api/audit-runs", params={"limit": 100}).json()["total"]
    assert after_total == before_total
    assert audit_run_snapshot(db_session) == before_snapshot


def test_export_review_read_failure_does_not_create_or_mutate_audit_run(db_session, monkeypatch):
    """A forced failure inside the real export read call path
    (`ReviewRepository.get_by_id`, the method `export_review` actually calls
    to fetch the review) must surface as the app's normal unhandled-error
    response, never as a written or mutated `audit_runs` row — CSV export
    failures are not audit events."""
    document = make_document(db_session)
    review = make_review(db_session, document_id=document.id)
    make_audit_run(db_session, action="document.create", status="success")
    before_snapshot = audit_run_snapshot(db_session)

    def _boom(self, review_id):
        raise RuntimeError("forced read failure for test")

    monkeypatch.setattr(ReviewRepository, "get_by_id", _boom)

    with TestClient(app, raise_server_exceptions=False) as local_client:
        response = local_client.get(f"/api/reviews/{review.id}/export")

    assert response.status_code == 500
    assert response.json() == {"detail": "Внутренняя ошибка сервера"}
    assert audit_run_snapshot(db_session) == before_snapshot

import csv
import io
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories.audit_repository import AuditRunRepository
from app.services.audit_service import validate_audit_invariant
from app.services.display_labels import format_datetime_ru, format_duration_ru, label_audit_action
from tests.helpers import audit_run_snapshot, make_audit_run


def _ordering_key(item: dict) -> tuple[str, str]:
    return (item["created_at"], item["id"])


def _parse_csv(content: bytes) -> list[list[str]]:
    text = content.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text), delimiter=";"))


def test_list_audit_runs_empty(client):
    response = client.get("/api/audit-runs")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_list_and_detail(client, db_session):
    audit_run = make_audit_run(
        db_session,
        action="document.create",
        status="success",
        entity_type="document",
        entity_id=str(uuid.uuid4()),
        input_json={"title": "t", "text": "x"},
        output_json={"id": "abc", "status": "created"},
    )

    list_response = client.get("/api/audit-runs")
    assert list_response.status_code == 200
    body = list_response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == audit_run.id
    assert body["items"][0]["input_json"] == {"title": "t", "text": "x"}

    detail_response = client.get(f"/api/audit-runs/{audit_run.id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == audit_run.id


def test_audit_run_nullable_entity_fields(client, db_session):
    audit_run = make_audit_run(
        db_session,
        action="ai.review",
        status="success",
        entity_type=None,
        entity_id=None,
        input_json=None,
        output_json=None,
    )

    response = client.get(f"/api/audit-runs/{audit_run.id}")
    body = response.json()
    assert body["entity_type"] is None
    assert body["entity_id"] is None
    assert body["input_json"] is None
    assert body["output_json"] is None


def test_get_audit_run_unknown_uuid_returns_404(client):
    response = client.get(f"/api/audit-runs/{uuid.uuid4()}")
    assert response.status_code == 404


def test_get_audit_run_invalid_uuid_returns_422(client):
    response = client.get("/api/audit-runs/not-a-uuid")
    assert response.status_code == 422


def test_action_filter(client, db_session):
    create_run = make_audit_run(db_session, action="document.create", status="success")
    make_audit_run(db_session, action="ai.review", status="success", entity_type="review")

    response = client.get("/api/audit-runs", params={"action": "document.create"})
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == create_run.id


def test_action_filter_omitted_is_allowed(client, db_session):
    make_audit_run(db_session, action="document.create", status="success")

    response = client.get("/api/audit-runs")
    assert response.status_code == 200
    assert response.json()["total"] == 1


def test_action_filter_valid_value(client, db_session):
    make_audit_run(db_session, action="document.create", status="success")
    make_audit_run(db_session, action="ai.review", status="success", entity_type="review")

    response = client.get("/api/audit-runs", params={"action": "ai.review"})
    assert response.status_code == 200
    assert response.json()["total"] == 1


def test_action_filter_trims_surrounding_whitespace(client, db_session):
    create_run = make_audit_run(db_session, action="document.create", status="success")

    response = client.get("/api/audit-runs", params={"action": "  document.create  "})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == create_run.id


def test_action_filter_empty_string_returns_422(client):
    response = client.get("/api/audit-runs", params={"action": ""})
    assert response.status_code == 422


def test_action_filter_whitespace_only_returns_422(client):
    response = client.get("/api/audit-runs", params={"action": "   "})
    assert response.status_code == 422


def test_status_filter(client, db_session):
    success_run = make_audit_run(db_session, action="document.create", status="success")
    make_audit_run(
        db_session,
        action="document.review",
        status="error",
        entity_type="document",
        error="model call failed",
    )

    response = client.get("/api/audit-runs", params={"status": "success"})
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == success_run.id


def test_invalid_status_returns_422(client):
    response = client.get("/api/audit-runs", params={"status": "bogus"})
    assert response.status_code == 422


def test_errors_only_true_returns_only_error_status(client, db_session):
    make_audit_run(db_session, action="document.create", status="success")
    make_audit_run(db_session, action="document.create", status="needs_review", error=None)
    error_run = make_audit_run(
        db_session,
        action="document.review",
        status="error",
        entity_type="document",
        error="upstream failure",
    )

    response = client.get("/api/audit-runs", params={"errors_only": "true"})
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == error_run.id
    assert body["items"][0]["status"] == "error"


def test_deterministic_ordering(client, db_session):
    for i in range(5):
        make_audit_run(db_session, action="document.create", status="success", entity_id=str(i))

    response = client.get("/api/audit-runs", params={"limit": 100})
    items = response.json()["items"]
    assert len(items) == 5
    keys = [_ordering_key(item) for item in items]
    assert keys == sorted(keys, reverse=True)


def test_filtered_total_before_pagination(client, db_session):
    for i in range(4):
        make_audit_run(db_session, action="document.create", status="success", entity_id=str(i))
    make_audit_run(db_session, action="ai.review", status="success", entity_type="review")

    response = client.get("/api/audit-runs", params={"action": "document.create", "limit": 2})
    body = response.json()
    assert body["total"] == 4
    assert len(body["items"]) == 2


def test_status_error_invariant_requires_error_message():
    with pytest.raises(ValueError):
        validate_audit_invariant("error", None)
    with pytest.raises(ValueError):
        validate_audit_invariant("error", "   ")


def test_status_error_invariant_forbids_error_on_success():
    with pytest.raises(ValueError):
        validate_audit_invariant("success", "should not be here")


def test_status_error_invariant_forbids_error_on_needs_review():
    with pytest.raises(ValueError):
        validate_audit_invariant("needs_review", "should not be here")


def test_status_error_invariant_allows_valid_combinations():
    validate_audit_invariant("success", None)
    validate_audit_invariant("needs_review", None)
    validate_audit_invariant("error", "sanitized summary")


# -----------------------------------------------------------------------------
# GET /api/audit-runs/export
# -----------------------------------------------------------------------------


def test_export_audit_runs_static_route_not_shadowed_by_uuid_detail_route(client):
    """REGRESSION: `/audit-runs/export` must hit the dedicated export handler,
    not the `/{audit_run_id}` detail route with audit_run_id="export" (which
    would fail UUID parsing with 422). Route registration order in
    app/api/audit_runs.py is what guarantees this."""
    response = client.get("/api/audit-runs/export")
    assert response.status_code == 200
    assert response.status_code != 422
    assert response.headers["content-type"].startswith("text/csv")


def test_export_audit_runs_does_not_create_audit_run(client, db_session):
    """CSV export is a read-only `GET` — it must never itself be recorded as
    an AuditRun row (it is not part of the audited write/action contract),
    and it must not mutate an already-existing audit row either. A plain
    `total` comparison would miss an in-place mutation (e.g. a row silently
    rewritten from status="success" to status="error") since row count alone
    is unchanged by that — the full snapshot comparison below catches it."""
    make_audit_run(db_session, action="document.create", status="success")
    before_total = client.get("/api/audit-runs", params={"limit": 100}).json()["total"]
    before_snapshot = audit_run_snapshot(db_session)

    response = client.get("/api/audit-runs/export")
    assert response.status_code == 200

    after_total = client.get("/api/audit-runs", params={"limit": 100}).json()["total"]
    assert after_total == before_total
    assert audit_run_snapshot(db_session) == before_snapshot


def test_export_audit_runs_read_failure_does_not_create_or_mutate_audit_run(db_session, monkeypatch):
    """A forced failure inside the real export read call path
    (`AuditRunRepository.list_all_for_export`, the method `export_audit_runs`
    actually calls) must surface as the app's normal unhandled-error
    response, never as a written or mutated `audit_runs` row — CSV export
    failures are not audit events."""
    make_audit_run(db_session, action="document.create", status="success")
    before_snapshot = audit_run_snapshot(db_session)

    def _boom(self, **kwargs):
        raise RuntimeError("forced read failure for test")

    monkeypatch.setattr(AuditRunRepository, "list_all_for_export", _boom)

    # Starlette's ServerErrorMiddleware re-raises the original exception after
    # sending our custom 500 response, so the default `client` fixture (which
    # asserts on that re-raise for debugging) would surface it as a test
    # failure instead of a response. raise_server_exceptions=False lets us
    # inspect the actual HTTP response the real client would receive —
    # mirrors test_documents.py::test_create_document_rolls_back_when_audit_persistence_fails.
    with TestClient(app, raise_server_exceptions=False) as local_client:
        response = local_client.get("/api/audit-runs/export")

    assert response.status_code == 500
    assert response.json() == {"detail": "Внутренняя ошибка сервера"}
    assert audit_run_snapshot(db_session) == before_snapshot


def test_export_audit_runs_empty_has_bom_and_header_only(client):
    response = client.get("/api/audit-runs/export")
    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    rows = _parse_csv(response.content)
    assert rows == [
        [
            "ID записи",
            "Операция",
            "Тип объекта",
            "ID объекта",
            "Статус",
            "Длительность",
            "Ошибка",
            "Дата и время",
            "Детали JSON",
        ]
    ]


def test_export_audit_runs_content_type_and_content_disposition(client):
    response = client.get("/api/audit-runs/export")
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="audit-runs-export.csv"'


def test_export_audit_runs_normal_row(client, db_session):
    audit_run = make_audit_run(
        db_session,
        action="document.create",
        status="success",
        entity_type="document",
        entity_id="doc-1",
        duration_ms=42,
        input_json={"title": "t"},
        output_json={"id": "doc-1"},
    )

    response = client.get("/api/audit-runs/export")
    rows = _parse_csv(response.content)
    assert len(rows) == 2
    data_row = rows[1]
    assert data_row[0] == audit_run.id
    assert data_row[1] == label_audit_action("document.create")
    assert data_row[2] == "Документ"
    assert data_row[3] == "doc-1"
    assert data_row[4] == "Успешно"
    assert data_row[5] == format_duration_ru(42)
    assert data_row[6] == ""
    assert data_row[7] == format_datetime_ru(audit_run.created_at)
    details = json.loads(data_row[8])
    assert details == {"input_json": {"title": "t"}, "output_json": {"id": "doc-1"}}


def test_export_audit_runs_null_duration_and_error_become_empty_or_zero(client, db_session):
    audit_run = make_audit_run(
        db_session,
        action="ai.review",
        status="success",
        entity_type=None,
        entity_id=None,
        duration_ms=0,
        error=None,
    )

    response = client.get("/api/audit-runs/export")
    rows = _parse_csv(response.content)
    data_row = rows[1]
    assert data_row[0] == audit_run.id
    assert data_row[2] == ""
    assert data_row[3] == ""
    assert data_row[5] == format_duration_ru(0)
    assert data_row[6] == ""


def test_export_audit_runs_error_row(client, db_session):
    audit_run = make_audit_run(
        db_session,
        action="document.review",
        status="error",
        entity_type="document",
        error="Сбой модели (сведения скрыты)",
    )

    response = client.get("/api/audit-runs/export")
    rows = _parse_csv(response.content)
    data_row = rows[1]
    assert data_row[0] == audit_run.id
    assert data_row[4] == "Техническая ошибка"
    assert data_row[6] == "Сбой модели (сведения скрыты)"


def test_export_audit_runs_action_filter(client, db_session):
    create_run = make_audit_run(db_session, action="document.create", status="success")
    make_audit_run(db_session, action="ai.review", status="success", entity_type="review")

    response = client.get("/api/audit-runs/export", params={"action": "document.create"})
    rows = _parse_csv(response.content)
    assert len(rows) == 2
    assert rows[1][0] == create_run.id


def test_export_audit_runs_status_filter(client, db_session):
    success_run = make_audit_run(db_session, action="document.create", status="success")
    make_audit_run(
        db_session, action="document.review", status="error", entity_type="document", error="fail"
    )

    response = client.get("/api/audit-runs/export", params={"status": "success"})
    rows = _parse_csv(response.content)
    assert len(rows) == 2
    assert rows[1][0] == success_run.id


def test_export_audit_runs_invalid_status_returns_422(client):
    response = client.get("/api/audit-runs/export", params={"status": "bogus"})
    assert response.status_code == 422


def test_export_audit_runs_errors_only(client, db_session):
    make_audit_run(db_session, action="document.create", status="success")
    error_run = make_audit_run(
        db_session, action="document.review", status="error", entity_type="document", error="fail"
    )

    response = client.get("/api/audit-runs/export", params={"errors_only": "true"})
    rows = _parse_csv(response.content)
    assert len(rows) == 2
    assert rows[1][0] == error_run.id
    assert rows[1][4] == "Техническая ошибка"


def test_export_audit_runs_status_and_errors_only_combination_is_accepted(client, db_session):
    """The list endpoint does not forbid passing `status` and `errors_only`
    together (no such invariant exists in the current API — see
    test_errors_only_true_returns_only_error_status and AuditRunRepository.list);
    the export endpoint must behave identically, not invent a new restriction."""
    error_run = make_audit_run(
        db_session, action="document.review", status="error", entity_type="document", error="fail"
    )
    make_audit_run(db_session, action="document.create", status="success")

    response = client.get(
        "/api/audit-runs/export", params={"status": "error", "errors_only": "true"}
    )
    assert response.status_code == 200
    rows = _parse_csv(response.content)
    assert len(rows) == 2
    assert rows[1][0] == error_run.id

    # A contradictory combination (status that isn't "error" AND errors_only)
    # ANDs both filters together, yielding no rows — same as the list endpoint.
    contradictory = client.get(
        "/api/audit-runs/export", params={"status": "success", "errors_only": "true"}
    )
    assert contradictory.status_code == 200
    assert _parse_csv(contradictory.content) == [_parse_csv(response.content)[0]]


def test_export_audit_runs_empty_action_returns_422(client):
    response = client.get("/api/audit-runs/export", params={"action": ""})
    assert response.status_code == 422


def test_export_audit_runs_details_json_deterministic(client, db_session):
    make_audit_run(
        db_session,
        action="document.review",
        status="success",
        input_json={"b": 1, "a": 2},
        output_json=None,
    )

    response = client.get("/api/audit-runs/export")
    rows = _parse_csv(response.content)
    assert rows[1][8] == '{"input_json": {"a": 2, "b": 1}, "output_json": null}'


def test_export_audit_runs_safe_formula_escaping(client, db_session):
    audit_run = make_audit_run(
        db_session,
        action="document.review",
        status="error",
        entity_type="document",
        entity_id="=cmd",
        error="+malicious",
    )

    response = client.get("/api/audit-runs/export")
    rows = _parse_csv(response.content)
    data_row = rows[1]
    assert data_row[0] == audit_run.id
    assert data_row[3] == "'=cmd"
    assert data_row[6] == "'+malicious"


def test_export_audit_runs_ignores_pagination_and_exports_all_matching_rows(client, db_session):
    for i in range(120):
        make_audit_run(db_session, action="document.create", status="success", entity_id=str(i))

    response = client.get("/api/audit-runs/export", params={"limit": 10, "offset": 0})
    rows = _parse_csv(response.content)
    assert len(rows) - 1 == 120


def test_export_audit_runs_stable_order_matches_list_endpoint(client, db_session):
    for i in range(5):
        make_audit_run(db_session, action="document.create", status="success", entity_id=str(i))

    list_response = client.get("/api/audit-runs", params={"limit": 100})
    list_ids = [item["id"] for item in list_response.json()["items"]]

    export_response = client.get("/api/audit-runs/export")
    rows = _parse_csv(export_response.content)
    export_ids = [row[0] for row in rows[1:]]

    assert export_ids == list_ids

import uuid

import pytest

from app.services.audit_service import validate_audit_invariant
from tests.helpers import make_audit_run


def _ordering_key(item: dict) -> tuple[str, str]:
    return (item["created_at"], item["id"])


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
    make_audit_run(db_session, action="review.export", status="success", entity_type="review")

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
    make_audit_run(db_session, action="review.export", status="success", entity_type="review")

    response = client.get("/api/audit-runs", params={"action": "review.export"})
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
    make_audit_run(db_session, action="review.export", status="success", entity_type="review")

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

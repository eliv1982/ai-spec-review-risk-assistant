import json
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import app
from app.models import AuditRun, Document
from app.services.audit_service import AuditService


def _ordering_key(item: dict) -> tuple[str, str]:
    return (item["created_at"], item["id"])


def test_create_document_success(client):
    response = client.post("/api/documents", json={"title": "Spec", "text": "Body text"})
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Spec"
    assert body["text"] == "Body text"
    assert body["status"] == "created"
    uuid.UUID(body["id"])
    assert body["created_at"].endswith("Z")


def test_create_document_trims_title_and_text(client):
    response = client.post("/api/documents", json={"title": "  Spec  ", "text": "  Body text  "})
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Spec"
    assert body["text"] == "Body text"


def test_create_document_missing_title_returns_422(client):
    response = client.post("/api/documents", json={"text": "Body text"})
    assert response.status_code == 422


def test_create_document_missing_text_returns_422(client):
    response = client.post("/api/documents", json={"title": "Spec"})
    assert response.status_code == 422


def test_create_document_missing_both_fields_returns_422(client):
    response = client.post("/api/documents", json={})
    assert response.status_code == 422


def test_create_document_blank_title_returns_422(client):
    response = client.post("/api/documents", json={"title": "   ", "text": "Body text"})
    assert response.status_code == 422


def test_create_document_blank_text_returns_422(client):
    response = client.post("/api/documents", json={"title": "Spec", "text": "   "})
    assert response.status_code == 422


def test_create_document_wrong_type_title_returns_422(client):
    response = client.post("/api/documents", json={"title": 12345, "text": "Body text"})
    assert response.status_code == 422


def test_create_document_wrong_type_text_returns_422(client):
    response = client.post("/api/documents", json={"title": "Spec", "text": ["not", "a", "string"]})
    assert response.status_code == 422


def test_create_document_wrong_type_null_returns_422(client):
    response = client.post("/api/documents", json={"title": None, "text": "Body text"})
    assert response.status_code == 422


def test_create_document_commits_document_and_audit_together(client):
    response = client.post("/api/documents", json={"title": "Spec", "text": "Body text"})
    assert response.status_code == 201
    document_id = response.json()["id"]

    audit_response = client.get("/api/audit-runs", params={"action": "document.create"})
    assert audit_response.status_code == 200
    matching = [
        row for row in audit_response.json()["items"] if row["entity_id"] == document_id
    ]
    assert len(matching) == 1
    audit_row = matching[0]
    assert audit_row["action"] == "document.create"
    assert audit_row["entity_type"] == "document"
    assert audit_row["entity_id"] == document_id
    assert audit_row["status"] == "success"
    assert audit_row["error"] is None
    assert audit_row["duration_ms"] >= 0


def test_create_document_audit_snapshot_does_not_leak_secrets_or_raw_text(client, db_session):
    secret_title = "OPENAI_API_KEY=sk-test-secret-value"
    secret_text = (
        "Authorization: Bearer very-secret-token\n"
        "OPENAI_API_KEY=sk-test-secret-value\n"
        "Please implement the feature described above."
    )

    response = client.post("/api/documents", json={"title": secret_title, "text": secret_text})
    assert response.status_code == 201
    document_id = response.json()["id"]

    # The document record itself must still store the full raw content.
    stored_document = db_session.get(Document, document_id)
    assert stored_document.title == secret_title
    assert stored_document.text == secret_text

    audit_run = db_session.execute(
        select(AuditRun).where(
            AuditRun.action == "document.create", AuditRun.entity_id == document_id
        )
    ).scalar_one()

    assert audit_run.input_json == {
        "title_length": len(secret_title),
        "text_length": len(secret_text),
    }
    assert audit_run.output_json == {"document_id": document_id, "status": "created"}

    raw_snapshot = json.dumps(audit_run.input_json) + json.dumps(audit_run.output_json)
    for secret in (
        "sk-test-secret-value",
        "very-secret-token",
        "Bearer",
        "OPENAI_API_KEY",
        secret_title,
        secret_text,
    ):
        assert secret not in raw_snapshot


def test_create_document_rolls_back_when_audit_persistence_fails(db_session, monkeypatch):
    def _boom(self, *args, **kwargs):
        raise RuntimeError("forced audit failure for test")

    monkeypatch.setattr(AuditService, "record", _boom)

    # Starlette's ServerErrorMiddleware re-raises the original exception after
    # sending our custom 500 response, so the default TestClient (which asserts
    # on that re-raise for debugging) would surface it as a test failure instead
    # of a response. raise_server_exceptions=False lets us inspect the actual
    # HTTP response the real client would receive.
    with TestClient(app, raise_server_exceptions=False) as local_client:
        response = local_client.post("/api/documents", json={"title": "Spec", "text": "Body text"})

    assert response.status_code == 500

    documents_count = db_session.scalar(select(func.count()).select_from(Document))
    audit_count = db_session.scalar(select(func.count()).select_from(AuditRun))
    assert documents_count == 0
    assert audit_count == 0


def test_get_document_by_id(client):
    created = client.post("/api/documents", json={"title": "Spec", "text": "Body text"}).json()

    response = client.get(f"/api/documents/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created


def test_get_document_unknown_uuid_returns_404(client):
    response = client.get(f"/api/documents/{uuid.uuid4()}")
    assert response.status_code == 404


def test_get_document_invalid_uuid_returns_422(client):
    response = client.get("/api/documents/not-a-uuid")
    assert response.status_code == 422


def test_list_documents_status_filter(client, db_session):
    created = client.post("/api/documents", json={"title": "A", "text": "Text A"}).json()
    other = client.post("/api/documents", json={"title": "B", "text": "Text B"}).json()

    db_document = db_session.get(Document, other["id"])
    db_document.status = "reviewed"
    db_session.commit()

    response = client.get("/api/documents", params={"status": "created"})
    assert response.status_code == 200
    body = response.json()
    ids = [item["id"] for item in body["items"]]
    assert created["id"] in ids
    assert other["id"] not in ids
    assert body["total"] == 1


def test_list_documents_invalid_status_returns_422(client):
    response = client.get("/api/documents", params={"status": "bogus"})
    assert response.status_code == 422


def test_list_documents_deterministic_ordering(client):
    for i in range(5):
        client.post("/api/documents", json={"title": f"Doc {i}", "text": f"Text {i}"})

    response = client.get("/api/documents", params={"limit": 100})
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 5
    keys = [_ordering_key(item) for item in items]
    assert keys == sorted(keys, reverse=True)


def test_list_documents_pagination_defaults(client):
    for i in range(3):
        client.post("/api/documents", json={"title": f"Doc {i}", "text": f"Text {i}"})

    response = client.get("/api/documents")
    body = response.json()
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert body["total"] == 3
    assert len(body["items"]) == 3


def test_list_documents_pagination_limit_and_offset(client):
    for i in range(5):
        client.post("/api/documents", json={"title": f"Doc {i}", "text": f"Text {i}"})

    first_page = client.get("/api/documents", params={"limit": 2, "offset": 0}).json()
    second_page = client.get("/api/documents", params={"limit": 2, "offset": 2}).json()

    assert len(first_page["items"]) == 2
    assert len(second_page["items"]) == 2
    assert first_page["total"] == 5
    assert second_page["total"] == 5
    first_ids = {item["id"] for item in first_page["items"]}
    second_ids = {item["id"] for item in second_page["items"]}
    assert first_ids.isdisjoint(second_ids)


def test_list_documents_limit_out_of_range_returns_422(client):
    assert client.get("/api/documents", params={"limit": 0}).status_code == 422
    assert client.get("/api/documents", params={"limit": 101}).status_code == 422


def test_list_documents_offset_out_of_range_returns_422(client):
    assert client.get("/api/documents", params={"offset": -1}).status_code == 422


def test_list_documents_pagination_wrong_type_returns_422(client):
    assert client.get("/api/documents", params={"limit": "abc"}).status_code == 422
    assert client.get("/api/documents", params={"offset": "abc"}).status_code == 422

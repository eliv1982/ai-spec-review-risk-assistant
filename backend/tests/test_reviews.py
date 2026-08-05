import uuid

from tests.helpers import make_document, make_review


def _ordering_key(item: dict) -> tuple[str, str]:
    return (item["created_at"], item["id"])


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

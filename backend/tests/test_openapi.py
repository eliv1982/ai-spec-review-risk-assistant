"""OpenAPI schema regression tests for the three CSV `/export` endpoints.

Runtime already returns `text/csv` (verified in test_reviews.py /
test_audit_runs.py by asserting the response `Content-Type` header). These
tests additionally verify the *published* OpenAPI schema matches — FastAPI
documents the success response's media type independently of what the
handler actually returns at runtime, so the two can silently drift apart
unless both are covered.
"""

EXPORT_PATHS = [
    "/api/reviews/export",
    "/api/reviews/{review_id}/export",
    "/api/audit-runs/export",
]


def _get_openapi_schema(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    return response.json()


def test_export_endpoints_document_text_csv_for_200(client):
    schema = _get_openapi_schema(client)
    for path in EXPORT_PATHS:
        responses = schema["paths"][path]["get"]["responses"]
        assert "200" in responses, f"{path} is missing a documented 200 response"
        content = responses["200"].get("content", {})
        assert "text/csv" in content, f"{path} does not document text/csv for 200"


def test_export_endpoints_do_not_document_application_json_for_200(client):
    schema = _get_openapi_schema(client)
    for path in EXPORT_PATHS:
        content = schema["paths"][path]["get"]["responses"]["200"].get("content", {})
        assert "application/json" not in content, (
            f"{path} still documents application/json for its 200 response"
        )


def test_export_endpoints_preserve_documented_422_error_response(client):
    schema = _get_openapi_schema(client)
    for path in EXPORT_PATHS:
        responses = schema["paths"][path]["get"]["responses"]
        assert "422" in responses, f"{path} lost its documented 422 validation error response"
        content = responses["422"].get("content", {})
        assert "application/json" in content

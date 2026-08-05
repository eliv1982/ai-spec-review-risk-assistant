from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.database import Base, engine
from app.main import app


def test_lifespan_startup_creates_database_schema():
    # Undo the autouse `_reset_database` fixture's pre-creation so this test
    # genuinely exercises the app's own lifespan/startup schema initialization
    # (init_db), not the test fixture that normally prepares a clean schema.
    Base.metadata.drop_all(bind=engine)
    assert inspect(engine).get_table_names() == []

    with TestClient(app) as test_client:
        response = test_client.get("/api/health")
        assert response.status_code == 200

    table_names = set(inspect(engine).get_table_names())
    assert table_names == {"documents", "reviews", "audit_runs"}


def test_health_returns_ok(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

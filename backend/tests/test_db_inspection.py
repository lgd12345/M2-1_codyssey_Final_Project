"""Admin-only metadata route checks; no database, credentials, or external HTTP.

Run this file with ``pytest --noconftest tests/test_db_inspection.py`` so the
existing corpus conftest does not load a local .env file.
"""
from unittest.mock import Mock
from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.auth.deps import require_user
from app.auth.service import AuthUser, LoginRequired, SessionInfo


PATH = "/api/v1/admin/db-inspection"
SAFE_METADATA = {
    "scope": "metadata_only",
    "databases": [
        {"alias": "business", "configured": True, "reachable": True},
        {"alias": "auth", "configured": True, "same_target_as": "business"},
    ],
    "ddl_executed": False,
}


@pytest.fixture
def database_guard(monkeypatch):
    connect = Mock(side_effect=AssertionError("these route tests must never connect to a database"))
    monkeypatch.setattr(psycopg, "connect", connect)
    yield connect
    connect.assert_not_called()


@pytest.fixture
def app(monkeypatch, database_guard):
    # Importing app.main also imports AgentSettings, whose module normally loads
    # .env. Disable that loader before importing the app, not after collection.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *_args, **_kwargs: False)

    from app.main import app as application

    monkeypatch.setattr(application, "dependency_overrides", {})
    monkeypatch.setattr(application, "openapi_schema", None)
    return application


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def set_session(app, role):
    if role is None:
        def anonymous():
            raise LoginRequired()
        app.dependency_overrides[require_user] = anonymous
        return

    session = SessionInfo(
        AuthUser(UUID("00000000-0000-0000-0000-000000000001"), "fixture-account", role),
        csrf_token="synthetic-test-value",
    )
    app.dependency_overrides[require_user] = lambda: session


@pytest.mark.parametrize("role, expected_status", [(None, 401), ("user", 403)])
def test_unauthorized_callers_cannot_invoke_metadata_reader(app, client, monkeypatch, role, expected_status):
    reader = Mock(side_effect=AssertionError("metadata must not be read before authorization"))
    monkeypatch.setattr("app.db_inspection.inspect_environment", reader)
    set_session(app, role)

    response = client.get(PATH)

    assert response.status_code == expected_status
    reader.assert_not_called()
    assert "set-cookie" not in response.headers


def test_admin_receives_only_reader_metadata_with_private_no_store_headers(app, client, monkeypatch):
    reader = Mock(return_value=SAFE_METADATA)
    monkeypatch.setattr("app.db_inspection.inspect_environment", reader)
    set_session(app, "admin")

    response = client.get(PATH)

    assert response.status_code == 200
    assert response.json() == SAFE_METADATA
    reader.assert_called_once()
    cache_directives = {part.strip().lower() for part in response.headers["cache-control"].split(",")}
    assert {"no-store", "private"} <= cache_directives
    assert "cookie" in {part.strip().lower() for part in response.headers["vary"].split(",")}
    assert "set-cookie" not in response.headers
    assert "fixture-account" not in response.text
    assert "synthetic-test-value" not in response.text


def test_inspection_route_is_not_advertised_in_openapi(client, monkeypatch):
    reader = Mock(side_effect=AssertionError("OpenAPI generation must not read database metadata"))
    monkeypatch.setattr("app.db_inspection.inspect_environment", reader)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert PATH not in response.json()["paths"]
    reader.assert_not_called()


def test_startup_and_existing_health_do_not_connect_to_database(client, monkeypatch):
    reader = Mock(side_effect=AssertionError("startup/health must not inspect the database"))
    monkeypatch.setattr("app.db_inspection.inspect_environment", reader)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    reader.assert_not_called()

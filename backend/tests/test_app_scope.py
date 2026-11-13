"""Mock-screen scope boundaries. No database, SMTP, embedding or LLM calls."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.deps import OperatorRequired, require_operator
from app.auth.service import AuthUser, SessionInfo
from app.main import app


RETIRED_PATHS = [
    ("GET", "/api/db-status"),
    ("GET", "/api/v1/admin/db-inspection"),
    ("GET", "/api/v1/documents"),
    ("GET", "/api/v1/companies"),
    ("GET", "/api/v1/companies/status"),
    ("GET", "/api/v1/companies/readiness"),
    ("GET", "/api/v1/companies/installation"),
    ("GET", "/api/v1/companies/customer-installation"),
    ("POST", "/api/v1/companies"),
    ("PUT", "/api/v1/companies/example"),
    ("POST", "/api/v1/companies/example/contacts"),
    ("POST", "/api/v1/companies/example/equipment"),
    ("GET", "/api/v1/access/status"),
    ("GET", "/api/v1/access/customer/profile"),
    ("POST", "/api/v1/access/challenges"),
    ("POST", "/api/v1/access/registration/verify"),
    ("POST", "/api/v1/access/registration"),
    ("GET", "/api/v1/access/guest/session"),
    ("POST", "/api/v1/access/guest/session"),
    ("GET", "/api/v1/access/guest/inquiry"),
    ("POST", "/api/v1/access/guest/inquiry"),
    ("POST", "/api/v1/agent/stream"),
]


@pytest.fixture
def client(monkeypatch):
    def unexpected_connect(*_args, **_kwargs):
        raise AssertionError("scope checks must not contact any database")

    monkeypatch.setattr("psycopg.connect", unexpected_connect)
    # Stale deployment flags must not bring retired features back.
    for name in ("COMPANY_ADMIN_ENABLED", "CUSTOMER_ACCESS_ENABLED",
                 "CUSTOMER_ACCESS_RELEASE_APPROVED", "CUSTOMER_REGISTRATION_ENABLED"):
        monkeypatch.setenv(name, "1")
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("method,path", RETIRED_PATHS)
def test_retired_workflows_are_not_exposed(client, method, path):
    response = client.request(method, path)
    # StaticFiles mounted at '/' may reject unmatched non-GET methods with 405.
    assert response.status_code in ({404} if method == "GET" else {404, 405})


def test_only_current_screen_and_analysis_routes_remain():
    routes = {(method.upper(), path)
              for path, operations in app.openapi()["paths"].items()
              for method in operations if path.startswith("/api/")}
    assert routes == {
        ("GET", "/api/health"),
        ("GET", "/api/v1/service-requests/context"),
        ("GET", "/api/v1/service-requests"),
        ("POST", "/api/v1/service-requests"),
        ("GET", "/api/v1/service-requests/{identity}"),
        ("POST", "/api/v1/service-requests/{identity}/analysis"),
        ("POST", "/api/v1/service-requests/{identity}/assignee"),
        ("POST", "/api/v1/service-requests/{identity}/comments"),
        ("POST", "/api/v1/service-requests/{identity}/approval"),
        ("POST", "/api/v1/service-requests/{identity}/decline"),
        ("POST", "/api/v1/service-requests/{identity}/reanalysis"),
        ("PATCH", "/api/v1/service-requests/{identity}/departments/{key}"),
        ("POST", "/api/v1/service-requests/{identity}/work/{work_key}/assignee"),
        ("POST", "/api/v1/service-requests/{identity}/work/{work_key}/start"),
        ("POST", "/api/v1/service-requests/{identity}/work/{work_key}/complete"),
        ("POST", "/api/v1/service-requests/{identity}/resolution"),
        ("POST", "/api/v1/service-requests/{identity}/replies"),
        ("POST", "/api/v1/service-requests/{identity}/callback"),
        ("POST", "/api/v1/service-requests/{identity}/close-request"),
        ("GET", "/api/v1/auth/me"),
        ("POST", "/api/v1/auth/login"),
        ("POST", "/api/v1/auth/logout"),
        ("POST", "/api/v1/agent/runs"),
        ("GET", "/api/v1/agent/runs"),
        ("GET", "/api/v1/agent/runs/{run_id}"),
        ("GET", "/api/v1/agent/runs/{run_id}/assets/{asset_id}"),
    }


def test_health_does_not_require_database_or_mail_settings(client):
    assert client.get("/api/health").json() == {"status": "ok"}


@pytest.mark.parametrize("role", ["user", "customer"])
def test_customer_roles_cannot_access_operator_analysis(role):
    session = SessionInfo(AuthUser(uuid4(), "customer", role), "csrf")
    with pytest.raises(OperatorRequired):
        require_operator(session)


def test_admin_can_access_operator_analysis():
    session = SessionInfo(AuthUser(uuid4(), "operator", "admin"), "csrf")
    assert require_operator(session) is session


@pytest.mark.parametrize("role", [None, "user", "customer"])
@pytest.mark.parametrize("method,path", [
    ("POST", "/api/v1/agent/runs"),
    ("GET", "/api/v1/agent/runs"),
    ("GET", "/api/v1/agent/runs/example"),
    ("GET", "/api/v1/agent/runs/example/assets/example"),
])
def test_analysis_api_rejects_anonymous_and_customers_before_database_or_llm(
    client, monkeypatch, role, method, path,
):
    session = SessionInfo(AuthUser(uuid4(), "customer", role), "csrf") if role else None
    monkeypatch.setattr("app.auth.deps.current_session", lambda _request: session)
    response = client.request(method, path, json={"question": "sample"}, headers={
        "Origin": "http://testserver", "X-CSRF-Token": "csrf",
    })
    assert response.status_code == (403 if role else 401)
    assert response.json()["code"] == ("OPERATOR_REQUIRED" if role else "LOGIN_REQUIRED")

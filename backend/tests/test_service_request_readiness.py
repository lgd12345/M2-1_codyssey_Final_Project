"""Missing schema must be explicit, never an automatic migration or demo fallback."""
from contextlib import contextmanager
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.auth.service import AuthUser, SessionInfo
from app.main import app


@pytest.mark.parametrize('method,path', [
    ('GET', '/api/v1/service-requests/context'),
    ('GET', '/api/v1/service-requests'),
    ('GET', '/api/v1/service-requests/CLM-001'),
    ('POST', '/api/v1/service-requests'),
])
def test_missing_schema_returns_503_without_demo_data_or_schema_changes(monkeypatch, method, path):
    @contextmanager
    def not_migrated():
        raise psycopg.errors.UndefinedTable('synthetic table missing')
        yield  # pragma: no cover

    def unexpected_connect(*_args, **_kwargs):
        raise AssertionError('No real database or automatic schema operations allowed')

    session = SessionInfo(AuthUser(uuid4(), 'staff', 'admin'), 'csrf')
    monkeypatch.setattr('app.auth.deps.current_session', lambda _request: session)
    monkeypatch.setattr('app.service_requests.routes.database', not_migrated)
    monkeypatch.setattr('psycopg.connect', unexpected_connect)
    response = TestClient(app).request(method, path, headers={
        'Origin': 'http://testserver', 'X-CSRF-Token': 'csrf',
    }, json={'equipment_id': str(uuid4()), 'reason': '공구 교환 이상', 'message': '증상'})
    assert response.status_code == 503
    assert response.json()['code'] == 'REQUESTS_NOT_READY'
    assert 'requests' not in response.json()

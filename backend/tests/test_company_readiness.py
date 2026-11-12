"""Preflight access boundaries and fail-closed summaries; no real DB or mail."""
from unittest.mock import MagicMock, Mock
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import psycopg
import pytest

from app.auth.deps import require_user
from app.auth.service import AuthUser, LoginRequired, SessionInfo
from app.company_admin import readiness, routes


PATH = '/api/v1/companies/readiness'
DSN = 'postgresql://synthetic-user:never-expose@private.invalid/synthetic-db'


@pytest.fixture
def database_guard(monkeypatch):
    connect = Mock(side_effect=AssertionError('No real database in these tests'))
    monkeypatch.setattr(psycopg, 'connect', connect)
    return connect


@pytest.mark.parametrize('role,status', [(None, 401), ('customer', 403), ('unexpected', 403), ('user', 200), ('admin', 200)])
def test_authorization_before_inspection_and_no_private_output(monkeypatch, database_guard, role, status):
    app = FastAPI()
    app.include_router(routes.router)
    def session():
        if role is None:
            raise LoginRequired()
        return SessionInfo(AuthUser(UUID(int=1), 'private-test-account', role), 'private-test-csrf')
    app.dependency_overrides[require_user] = session
    expected = readiness.inspect_readiness({})
    reader = Mock(return_value=expected)
    monkeypatch.setattr(routes, 'inspect_readiness', reader)
    with TestClient(app) as client:
        response = client.get(PATH)
        assert PATH not in client.get('/openapi.json').json()['paths']
    assert response.status_code == status
    assert 'no-store' in response.headers['cache-control']
    assert response.headers['vary'] == 'Cookie'
    assert 'set-cookie' not in response.headers
    assert 'private-test' not in response.text
    if status == 200:
        assert response.json() == expected
        reader.assert_called_once()
    else:
        reader.assert_not_called()
    database_guard.assert_not_called()


@pytest.mark.parametrize('env,expected', [
    ({}, 'business_not_configured'),
    ({'DATABASE_URL':'  business  '}, 'same_connection_settings'),
    ({'DATABASE_URL':'business', 'RAG_DATABASE_URL':' business '}, 'same_connection_settings'),
    ({'DATABASE_URL':'business', 'RAG_DATABASE_URL':'equivalent-but-different-text'}, 'different_connection_settings'),
    ({'DATABASE_URL':'business', 'RAG_DATABASE_URL':' '}, 'auth_not_configured'),
])
def test_compatibility_is_only_the_existing_configuration_gate(monkeypatch, env, expected):
    reader = Mock(return_value={'connection':'unverified'})
    monkeypatch.setattr(readiness, '_database', reader)
    result = readiness.inspect_readiness(env)
    assert result['auth_configuration'] == expected
    assert result['write_checks_performed'] is False
    reader.assert_called_once_with(env.get('DATABASE_URL','').strip())
    assert not any(result['feature_flags'].values())


def test_missing_configuration_never_connects(database_guard):
    result = readiness.inspect_readiness({})
    assert result['database']['connection'] == 'not_configured'
    assert result['database']['schema'] == 'unverified'
    assert set(result['database']['migrations'].values()) == {'unverified'}
    assert set(result['database']['permission_checks'].values()) == {None}
    assert not any(result['server_settings_present'].values())
    database_guard.assert_not_called()


def test_server_settings_report_only_presence_and_never_read_files(database_guard, monkeypatch):
    monkeypatch.setattr('pathlib.Path.read_text', Mock(side_effect=AssertionError('No policy or credential file reads')))
    values = {'CUSTOMER_SMTP_USERNAME':'private@example.org','CUSTOMER_SMTP_PASSWORD':'synthetic-private-password',
              'CUSTOMER_ACCESS_SECRET':'synthetic-private-secret','CUSTOMER_ACCESS_POLICY_FILE':'/private/policy.json'}
    result = readiness.inspect_readiness(values)
    assert all(result['server_settings_present'].values())
    assert all(value not in str(result) for value in values.values())
    database_guard.assert_not_called()


@pytest.mark.parametrize('error', [psycopg.OperationalError(DSN), psycopg.ProgrammingError(DSN), OSError(DSN), ValueError(DSN)])
def test_connection_failure_is_sanitized_and_not_reported_as_missing(monkeypatch, error):
    monkeypatch.setattr(psycopg, 'connect', Mock(side_effect=error))
    result = readiness.inspect_readiness({'DATABASE_URL':DSN})
    assert result['database']['connection'] == 'failed'
    assert result['database']['schema'] == 'unverified'
    assert set(result['database']['migrations'].values()) == {'unverified'}
    assert all(value not in str(result) for value in ('never-expose','private.invalid','synthetic-user','synthetic-db'))


def test_unconfirmed_read_only_stops_before_metadata(monkeypatch):
    connect = MagicMock()
    connection = connect.return_value.__enter__.return_value
    connection.execute.return_value.fetchone.return_value = ('off',)
    monkeypatch.setattr(psycopg, 'connect', connect)
    result = readiness.inspect_readiness({'DATABASE_URL':DSN})['database']
    assert result['connection'] == 'ok' and result['read_only'] is False
    assert result['schema'] == 'unverified'
    queries = [call.args[0] for call in connection.execute.call_args_list]
    assert queries == ['SET TRANSACTION READ ONLY', "SET LOCAL statement_timeout = '2s'",
                       "SET LOCAL lock_timeout = '500ms'", 'SHOW transaction_read_only']
    connect.assert_called_once_with(DSN, connect_timeout=3, autocommit=True)


@pytest.mark.parametrize('error', [psycopg.errors.InsufficientPrivilege(DSN), psycopg.errors.QueryCanceled(DSN)])
def test_metadata_errors_after_connection_leave_schema_unknown(monkeypatch, error):
    connect = MagicMock()
    connection = connect.return_value.__enter__.return_value
    def execute(query, *args):
        if query.startswith('SELECT'):
            raise error
        cursor = Mock()
        cursor.fetchone.return_value = ('on',)
        return cursor
    connection.execute.side_effect = execute
    monkeypatch.setattr(psycopg, 'connect', connect)
    result = readiness.inspect_readiness({'DATABASE_URL':DSN})['database']
    assert result['connection'] == 'ok' and result['read_only'] is True
    assert result['schema'] == result['required_tables'] == 'unverified'
    assert set(result['migrations'].values()) == {'unverified'}
    assert 'never-expose' not in str(result)

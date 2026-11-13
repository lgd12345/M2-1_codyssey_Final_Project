import pytest

from scripts.test_live_intake import validate_target


@pytest.fixture(autouse=True)
def no_database_connections(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError('Target validation must never connect or mutate a database')
    monkeypatch.setattr('psycopg.connect', forbidden)


@pytest.mark.parametrize('url', ['http://localhost:4173', 'http://127.0.0.1:4173/'])
def test_live_runner_accepts_only_explicit_current_target(url):
    assert validate_target('postgresql://example/service_poc_test', url, 'service_poc_test') == url.rstrip('/')


@pytest.mark.parametrize('dsn,url,approval', [
    ('postgresql://example/service_poc_test', 'http://localhost:4173', None),
    ('postgresql://example/service_poc_test', 'http://localhost:4173', 'service_poc'),
    ('postgresql://example/service_poc', 'http://localhost:4173', 'service_poc_test'),
    ('postgresql://example/rag_regression_abc_test', 'http://localhost:4173', 'service_poc_test'),
    ('postgresql://example/service_poc_test', 'https://external.example', 'service_poc_test'),
    ('postgresql://example/service_poc_test', 'http://localhost.external.example:4173', 'service_poc_test'),
    ('postgresql://example/service_poc_test', 'http://user:password@localhost:4173', 'service_poc_test'),
    ('postgresql://example/service_poc_test', 'file:///localhost', 'service_poc_test'),
    ('postgresql://example/service_poc_test', 'http://localhost:4173/path', 'service_poc_test'),
    ('postgresql://example/service_poc_test', 'http://localhost:4173/?target=elsewhere', 'service_poc_test'),
    ('postgresql://example/service_poc_test', 'http://localhost:4173/#/login', 'service_poc_test'),
])
def test_live_runner_rejects_unapproved_targets_before_any_connection(dsn, url, approval):
    with pytest.raises(ValueError):
        validate_target(dsn, url, approval)

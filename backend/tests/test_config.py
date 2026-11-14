"""One variable names the application database, and startup says so (by name, never with credentials)."""
import pytest

from app.config import application_database_url, check_configuration, startup_notes

APP = 'postgresql://app_user:s3cret@db.internal:5433/service_prod'
OLD = 'postgresql://rag_user:t0ken@db.internal:5433/service_poc_test'


def test_the_application_database_is_database_url_and_nothing_else():
    assert application_database_url({'DATABASE_URL': f' {APP} '}) == APP
    assert application_database_url({}) == ''
    assert application_database_url({'RAG_DATABASE_URL': OLD}) == ''  # the old variable is not a fallback
    assert application_database_url({'TEST_DATABASE_URL': OLD}) == ''


def test_every_consumer_resolves_the_database_the_same_way(monkeypatch):
    seen = []
    monkeypatch.setattr('psycopg.connect', lambda url, **_: seen.append(url) or object())
    monkeypatch.setenv('DATABASE_URL', APP)
    monkeypatch.delenv('RAG_DATABASE_URL', raising=False)
    from app.agent_rag.db import connect_database
    from app.agent_rag.settings import AgentSettings
    from app.auth.deps import database_url
    connect_database()
    assert seen == [APP] and database_url() == APP and AgentSettings.from_env().database_url == APP


def test_connecting_without_configuration_fails_naming_the_variable_to_set(monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.delenv('RAG_DATABASE_URL', raising=False)
    from app.agent_rag.db import connect_database
    with pytest.raises(RuntimeError, match='DATABASE_URL'):
        connect_database()


# ---------- the retired RAG_DATABASE_URL must not silently switch databases ----------

def test_a_leftover_rag_database_url_that_differs_stops_startup_with_the_fix():
    with pytest.raises(RuntimeError) as stopped:
        check_configuration({'DATABASE_URL': APP, 'RAG_DATABASE_URL': OLD})
    message = str(stopped.value)
    assert 'RAG_DATABASE_URL' in message and 'DATABASE_URL' in message and 'no longer' in message
    for secret in ('s3cret', 't0ken', 'rag_user', 'db.internal'):
        assert secret not in message
    with pytest.raises(RuntimeError):  # it used to win, so ignoring it when DATABASE_URL is missing would also switch
        check_configuration({'RAG_DATABASE_URL': OLD})


@pytest.mark.parametrize('env', [{'DATABASE_URL': APP}, {'DATABASE_URL': APP, 'RAG_DATABASE_URL': APP},
                                 {'DATABASE_URL': APP, 'RAG_DATABASE_URL': '  '}, {}])
def test_consistent_or_absent_settings_do_not_stop_startup(env):
    check_configuration(env)


def test_the_application_refuses_to_start_on_a_conflicting_leftover(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setenv('DATABASE_URL', APP)
    monkeypatch.setenv('RAG_DATABASE_URL', OLD)
    with pytest.raises(RuntimeError, match='no longer'):
        with TestClient(app):
            pass


# ---------- startup notes ----------

def notes(**env):
    return startup_notes(env)


def test_startup_names_the_database_in_use_without_credentials():
    result = notes(DATABASE_URL=APP)
    assert result == [('info', 'application database: service_prod (DATABASE_URL)')]
    text = ' '.join(message for _level, message in result)
    for secret in ('s3cret', 'app_user', 'db.internal', '5433'):
        assert secret not in text


def test_a_redundant_rag_database_url_is_called_out_for_removal():
    result = notes(DATABASE_URL=APP, RAG_DATABASE_URL=APP)
    warning = [message for level, message in result if level == 'warning']
    assert len(warning) == 1 and 'RAG_DATABASE_URL' in warning[0] and 'remove' in warning[0]


def test_a_test_database_variable_that_points_at_the_application_database_is_called_out():
    warning = [m for level, m in notes(DATABASE_URL=APP, TEST_DATABASE_URL=APP) if level == 'warning']
    assert len(warning) == 1 and 'TEST_DATABASE_URL' in warning[0] and 'test_isolated' in warning[0]
    assert not [1 for level, _ in notes(DATABASE_URL=APP, TEST_DATABASE_URL=OLD) if level == 'warning']


def test_missing_database_configuration_is_reported():
    assert notes() == [('warning', 'no application database is configured (set DATABASE_URL)')]


@pytest.mark.parametrize('workers,warns', [('1', False), ('', False), ('abc', False), ('2', True), ('8', True)])
def test_more_than_one_worker_is_flagged_because_analysis_recovery_assumes_a_single_process(workers, warns):
    env = {'DATABASE_URL': APP}
    if workers:
        env['WEB_CONCURRENCY'] = workers
    warnings = [message for level, message in startup_notes(env) if level == 'warning']
    assert bool(warnings) is warns
    if warns:
        assert 'single' in warnings[0] and 'analysis' in warnings[0] and workers in warnings[0]


def test_startup_notes_are_logged_where_uvicorn_shows_them_including_info(monkeypatch, caplog):
    import logging
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setenv('DATABASE_URL', OLD)
    monkeypatch.delenv('RAG_DATABASE_URL', raising=False)
    monkeypatch.delenv('WEB_CONCURRENCY', raising=False)
    with caplog.at_level(logging.INFO, logger='uvicorn.error'):
        with TestClient(app):
            pass
    messages = [record.getMessage() for record in caplog.records if record.name == 'uvicorn.error']
    assert 'application database: service_poc_test (DATABASE_URL)' in messages
    assert not [m for m in messages if 's3cret' in m or 't0ken' in m or 'db.internal' in m]

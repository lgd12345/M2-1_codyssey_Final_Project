"""One rule for which database the application uses, and startup notes that name the traps without leaking secrets."""
import pytest

from app.config import application_database_url, startup_notes

APP = 'postgresql://app_user:s3cret@db.internal:5433/service_prod'
RAG = 'postgresql://rag_user:t0ken@db.internal:5433/service_poc_test'


def test_the_application_database_is_rag_database_url_first_then_database_url():
    assert application_database_url({'RAG_DATABASE_URL': RAG, 'DATABASE_URL': APP}) == RAG
    assert application_database_url({'DATABASE_URL': APP}) == APP
    assert application_database_url({'RAG_DATABASE_URL': '  ', 'DATABASE_URL': f' {APP} '}) == APP
    assert application_database_url({}) == ''


def test_test_database_url_is_never_the_application_database():
    assert application_database_url({'TEST_DATABASE_URL': RAG}) == ''


def test_every_consumer_resolves_the_database_the_same_way(monkeypatch):
    seen = []
    monkeypatch.setattr('psycopg.connect', lambda url, **_: seen.append(url) or object())
    monkeypatch.setenv('RAG_DATABASE_URL', RAG)
    monkeypatch.setenv('DATABASE_URL', APP)
    from app.agent_rag.db import connect_database
    from app.agent_rag.settings import AgentSettings
    from app.auth.deps import database_url
    connect_database()
    assert seen == [RAG] and database_url() == RAG and AgentSettings.from_env().database_url == RAG


def test_connecting_without_any_configuration_fails_with_the_names_to_set(monkeypatch):
    monkeypatch.delenv('RAG_DATABASE_URL', raising=False)
    monkeypatch.delenv('DATABASE_URL', raising=False)
    from app.agent_rag.db import connect_database
    with pytest.raises(RuntimeError, match='RAG_DATABASE_URL or DATABASE_URL'):
        connect_database()


def notes(**env):
    return startup_notes(env)


def test_startup_names_the_database_in_use_and_the_one_it_ignores_without_credentials():
    result = notes(RAG_DATABASE_URL=RAG, DATABASE_URL=APP)
    text = ' '.join(message for _level, message in result)
    assert 'service_poc_test' in text and 'RAG_DATABASE_URL' in text
    assert 'service_prod' in text and 'ignored' in text  # the trap: DATABASE_URL is not what the app uses
    for secret in ('s3cret', 't0ken', 'app_user', 'rag_user', 'db.internal', '5433'):
        assert secret not in text
    assert all(level == 'info' for level, message in result if 'ignored' in message)


def test_a_single_database_variable_needs_no_warning():
    assert notes(DATABASE_URL=APP) == [('info', 'application database: service_prod (DATABASE_URL)')]
    assert notes(RAG_DATABASE_URL=RAG, DATABASE_URL=RAG)[0][1].startswith('application database: service_poc_test')
    assert len(notes(RAG_DATABASE_URL=RAG, DATABASE_URL=RAG)) == 1


def test_a_test_database_variable_that_points_at_the_application_database_is_called_out():
    result = notes(RAG_DATABASE_URL=RAG, TEST_DATABASE_URL=RAG)
    warning = [message for level, message in result if level == 'warning']
    assert len(warning) == 1 and 'TEST_DATABASE_URL' in warning[0] and 'test_isolated' in warning[0]
    assert not [1 for level, _ in notes(RAG_DATABASE_URL=RAG, TEST_DATABASE_URL=APP) if level == 'warning']


def test_missing_database_configuration_is_reported():
    assert notes() == [('warning', 'no application database is configured (set RAG_DATABASE_URL or DATABASE_URL)')]


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
    monkeypatch.setenv('RAG_DATABASE_URL', RAG)
    monkeypatch.setenv('DATABASE_URL', APP)
    monkeypatch.delenv('WEB_CONCURRENCY', raising=False)
    with caplog.at_level(logging.INFO, logger='uvicorn.error'):
        with TestClient(app):
            pass
    messages = [record.getMessage() for record in caplog.records if record.name == 'uvicorn.error']
    assert 'application database: service_poc_test (RAG_DATABASE_URL)' in messages
    assert any('service_prod' in message and 'ignored' in message for message in messages)
    assert not [m for m in messages if 's3cret' in m or 't0ken' in m or 'db.internal' in m]

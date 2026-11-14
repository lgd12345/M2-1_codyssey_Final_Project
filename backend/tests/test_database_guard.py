"""Regression tests TRUNCATE tables. They must never run against a database an application uses."""
import pytest

import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from db_safety import guard_test_database, is_disposable_test_database, require_disposable_test_database

DISPOSABLE = 'postgresql://u:p@host:5433/rag_regression_0123456789abcdef_test'


@pytest.mark.parametrize('url,expected', [
    (DISPOSABLE, True),
    ('postgresql://u:p@host/rag_regression_abc123_test', True),
    ('postgresql://u:p@host/service_poc_test', False),   # ends in _test but is the application's database
    ('postgresql://u:p@host/service_poc', False),
    ('postgresql://u:p@host/rag_regression_ABC_test', False),
    ('postgresql://u:p@host/rag_regression__test', False),
    ('postgresql://u:p@host/not_rag_regression_abc_test', False),
    ('postgresql://u:p@host/', False),
    ('', False),
    ('host=h port=5433 user=u password=p dbname=rag_regression_0123456789abcdef_test', True),  # runner format
    ('host=h dbname=service_poc_test user=u', False),
    ('not a connection string', False),
])
def test_only_runner_created_disposable_databases_are_accepted(url, expected):
    assert is_disposable_test_database(url) is expected


def test_guard_removes_a_non_disposable_url_so_database_tests_skip_instead_of_truncating():
    environment = {'TEST_DATABASE_URL': 'postgresql://u:p@host/service_poc_test', 'DATABASE_URL': 'postgresql://u:p@host/service_poc_test'}
    message = guard_test_database(environment)
    assert environment['TEST_DATABASE_URL'] == ''  # present-but-empty: database tests skip
    assert environment['DATABASE_URL'].endswith('service_poc_test')  # the application setting is never touched
    assert 'scripts/test_isolated.py' in message and 'service_poc_test' not in message  # no database name leaks into logs


def test_guard_keeps_the_runner_database_and_is_silent_without_a_url():
    environment = {'TEST_DATABASE_URL': DISPOSABLE}
    assert guard_test_database(environment) == ''
    assert environment['TEST_DATABASE_URL'] == DISPOSABLE
    assert guard_test_database({}) == ''


def test_a_later_dotenv_load_cannot_bring_the_application_database_back(monkeypatch):
    """Application modules call load_dotenv(.env, override=False) when imported. A deleted variable would be
    restored from .env; an empty one is kept, so every later test module still sees 'not configured'."""
    monkeypatch.setenv('TEST_DATABASE_URL', 'postgresql://u:p@host/service_poc_test')
    guard_test_database(os.environ)
    with tempfile.TemporaryDirectory() as folder:
        dotenv = Path(folder) / '.env'
        dotenv.write_text('TEST_DATABASE_URL=postgresql://u:p@host/service_poc_test\n', encoding='utf-8')
        load_dotenv(dotenv, override=False)
    assert os.environ['TEST_DATABASE_URL'] == ''


def test_fixtures_refuse_to_truncate_anything_but_a_disposable_database():
    require_disposable_test_database(DISPOSABLE)
    for url in ['postgresql://u:p@host/service_poc_test', 'postgresql://u:p@host/service_poc', '']:
        with pytest.raises(RuntimeError, match='disposable'):
            require_disposable_test_database(url)

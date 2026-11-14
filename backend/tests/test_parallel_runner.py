"""Concurrency must preserve isolation and clean up after partial provisioning failures."""
from threading import Barrier
from types import SimpleNamespace

import pytest

from scripts import test_isolated as runner

BASE = 'postgresql://test:example@localhost/disposable_test'


@pytest.mark.parametrize('create', [True, False])
def test_database_operations_actually_overlap_on_independent_connections(monkeypatch, create):
    barrier = Barrier(4, timeout=5)
    calls = []
    connections = []

    class Connection:
        def __enter__(self):
            connections.append(self)
            return self

        def __exit__(self, *args):
            pass

        def execute(self, statement):
            barrier.wait()  # a sequential implementation cannot satisfy this barrier
            calls.append(statement.as_string())

    monkeypatch.setattr(runner.psycopg, 'connect', lambda *args, **kwargs: Connection())
    names = [f'rag_regression_{i}_test' for i in range(4)]
    runner.database_jobs(BASE, names, create=create)
    assert len(connections) == len({id(connection) for connection in connections}) == 4
    assert len(calls) == 4
    assert all(('CREATE DATABASE' if create else 'DROP DATABASE IF EXISTS') in call for call in calls)
    assert all(any(name in call for call in calls) for name in names)


@pytest.mark.parametrize('names', [['rag_regression_safe_test', 'service_poc_test'], ['production']])
def test_database_job_list_is_validated_before_any_connection(monkeypatch, names):
    def forbidden(*args, **kwargs):
        raise AssertionError('must validate the entire job list before connecting')
    monkeypatch.setattr(runner.psycopg, 'connect', forbidden)
    with pytest.raises(ValueError, match='non-disposable'):
        runner.database_jobs(BASE, names, create=True)


def test_partial_create_failure_still_attempts_cleanup_for_every_generated_name(monkeypatch):
    calls = []
    monkeypatch.setenv('TEST_DATABASE_URL', BASE)
    monkeypatch.setattr(runner.sys, 'argv', ['test_isolated.py', '--workers', '3'])

    def jobs(base, names, *, create):
        calls.append((create, names.copy()))
        if create:
            raise RuntimeError('synthetic partial failure')

    monkeypatch.setattr(runner, 'database_jobs', jobs)
    assert runner.main() == 2
    assert calls[0][0] is True and calls[1][0] is False
    assert calls[0][1] == calls[1][1] and len(calls[0][1]) == 3


def test_runner_passes_actual_worker_count_to_browser_shards(monkeypatch, tmp_path):
    monkeypatch.setenv('TEST_DATABASE_URL', BASE)
    monkeypatch.setattr(runner.sys, 'argv', ['test_isolated.py', '--workers', '6', 'tests'])
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    monkeypatch.setattr(runner, 'database_jobs', lambda *args, **kwargs: None)
    environments = []

    def run(*args, **kwargs):
        environments.append(kwargs['env'])
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(runner.subprocess, 'run', run)
    assert runner.main() == 0
    assert environments[0]['TEST_WORKERS'] == '6'
    import json
    assert len(json.loads(environments[0]['REGRESSION_DATABASES'])) == 6

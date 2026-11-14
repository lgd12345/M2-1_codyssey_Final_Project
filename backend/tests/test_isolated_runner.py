import pytest

from scripts.test_isolated import redact_output, regression_database_dsn


def test_runner_redacts_connection_strings_and_password_variants():
    base = "postgresql://user:private%2Fpassword@host/service_test"
    output = f"{base}\npassword=private/password\napi-private-value"
    result = redact_output(output, {"TEST_DATABASE_URL": base, "LLM_API_KEY": "api-private-value"})
    assert "private" not in result
    assert result.count("[REDACTED]") == 3


def test_runner_retargets_only_a_disposable_test_database():
    from psycopg.conninfo import conninfo_to_dict

    base = "postgresql://user:example@host/service_test"
    result = regression_database_dsn(base, "rag_regression_abc_test")
    assert conninfo_to_dict(result)["dbname"] == "rag_regression_abc_test"
    with pytest.raises(ValueError, match="isolated"):
        regression_database_dsn("postgresql://host/production", "rag_regression_abc_test")
    with pytest.raises(ValueError, match="disposable"):
        regression_database_dsn(base, "service_test")


# ---------- parallel runs: every worker gets its own disposable database ----------

def test_worker_count_comes_from_the_runner_flag_and_is_not_passed_on_to_pytest():
    from scripts.test_isolated import split_worker_option
    assert split_worker_option(['tests', '-q'], default=4) == (4, ['tests', '-q'])
    assert split_worker_option(['--workers', '3', 'tests', '-q'], default=4) == (3, ['tests', '-q'])
    assert split_worker_option(['tests', '--workers=1'], default=4) == (1, ['tests'])
    for bad in (['--workers'], ['--workers', 'x'], ['--workers', '0'], ['--workers', '33']):
        with pytest.raises(ValueError):
            split_worker_option(bad, default=4)


def test_pytest_gets_xdist_only_when_there_is_more_than_one_worker():
    from scripts.test_isolated import pytest_arguments
    assert pytest_arguments(1, ['tests', '-q']) == ['tests', '-q']
    assert pytest_arguments(4, ['tests', '-q']) == ['-n', '4', '--maxschedchunk=2', 'tests', '-q']
    assert pytest_arguments(4, ['-n', '2', 'tests']) == ['-n', '2', 'tests']  # an explicit choice wins


def test_each_worker_is_pointed_at_its_own_database_and_the_application_setting_follows():
    from db_safety import assign_worker_database
    urls = [f'host=h dbname=rag_regression_{n}_test' for n in ('aaa', 'bbb', 'ccc')]
    import json
    for worker, expected in [('gw0', 0), ('gw1', 1), ('gw2', 2)]:
        environment = {'REGRESSION_DATABASES': json.dumps(urls), 'PYTEST_XDIST_WORKER': worker, 'DATABASE_URL': 'application'}
        assign_worker_database(environment)
        assert environment['TEST_DATABASE_URL'] == environment['DATABASE_URL'] == urls[expected]
    single = {'REGRESSION_DATABASES': json.dumps(urls[:1])}  # no xdist: the first (only) database
    assign_worker_database(single)
    assert single['TEST_DATABASE_URL'] == urls[0]


def test_worker_database_assignment_never_invents_or_widens_access():
    from db_safety import assign_worker_database
    untouched = {'TEST_DATABASE_URL': 'x', 'DATABASE_URL': 'y'}
    assign_worker_database(untouched)  # not started by the runner: nothing changes
    assert untouched == {'TEST_DATABASE_URL': 'x', 'DATABASE_URL': 'y'}
    for bad in ('not json', '[]', '["host=h dbname=service_poc_test"]', '"text"'):
        environment = {'REGRESSION_DATABASES': bad, 'PYTEST_XDIST_WORKER': 'gw0', 'DATABASE_URL': 'application'}
        with pytest.raises(RuntimeError):
            assign_worker_database(environment)
        assert environment['DATABASE_URL'] == 'application'
    with pytest.raises(RuntimeError, match='more workers'):
        assign_worker_database({'REGRESSION_DATABASES': '["host=h dbname=rag_regression_a_test"]', 'PYTEST_XDIST_WORKER': 'gw3'})


def test_browser_shards_are_paired_with_short_tests_for_xdist_initial_batches():
    from types import SimpleNamespace
    from conftest import pytest_collection_modifyitems
    browser = [SimpleNamespace(nodeid=f'tests/test_service_requests_e2e.py::test_browser[{i}]') for i in range(4)]
    short = [SimpleNamespace(nodeid=f'tests/test_unit.py::test_{i}') for i in range(6)]
    items = short + browser
    pytest_collection_modifyitems(items)
    assert items == [browser[0], short[0], browser[1], short[1], browser[2], short[2], browser[3], short[3], *short[4:]]
    only_short = short.copy()
    pytest_collection_modifyitems(only_short)
    assert only_short == short


def test_production_password_hashing_keeps_the_library_defaults():
    # The tests use a cheap hasher (tests/conftest.py); the application must never be given that shortcut.
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / 'app' / 'auth' / 'service.py').read_text(encoding='utf-8')
    assert 'PasswordHash((Argon2Hasher(),))' in source

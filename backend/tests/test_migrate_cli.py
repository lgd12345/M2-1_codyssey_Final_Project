import pytest

from scripts import migrate


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    def forbidden(*_a, **_k):
        raise AssertionError('argument validation must not connect to a database')
    monkeypatch.setattr(migrate, 'apply_migrations', forbidden)


@pytest.mark.parametrize('env_name', ['DATABASE_URL'])
def test_application_databases_are_never_migrated_without_explicit_approval(monkeypatch, env_name):
    monkeypatch.setenv(env_name, 'postgresql://u:p@host/service_poc')
    monkeypatch.setattr('sys.argv', ['migrate.py', '--env-name', env_name])
    with pytest.raises(SystemExit) as stopped:
        migrate.main()
    assert stopped.value.code == 2


def test_database_url_is_the_database_the_running_app_uses(monkeypatch):
    applied = []
    monkeypatch.setattr(migrate, 'apply_migrations', lambda url: applied.append(url) or ['015_next'])
    monkeypatch.setenv('DATABASE_URL', 'postgresql://u:p@host/service_poc_test')
    monkeypatch.setattr('sys.argv', ['migrate.py', '--env-name', 'DATABASE_URL', '--allow-non-test'])
    assert migrate.main() == 0
    assert applied == ['postgresql://u:p@host/service_poc_test']


def test_test_database_urls_must_still_end_in_test(monkeypatch):
    monkeypatch.setenv('TEST_DATABASE_URL', 'postgresql://u:p@host/production')
    monkeypatch.setattr('sys.argv', ['migrate.py'])
    with pytest.raises(SystemExit) as stopped:
        migrate.main()
    assert stopped.value.code == 2

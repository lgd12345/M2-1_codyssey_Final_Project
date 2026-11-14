import os

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict


DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="isolated TEST_DATABASE_URL not configured")
PASSWORD = "correct-horse-battery"


@pytest.fixture
def db(monkeypatch, service_schema):
    from db_safety import require_disposable_test_database
    require_disposable_test_database(DATABASE_URL)
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    connection = psycopg.connect(DATABASE_URL)
    connection.execute("TRUNCATE app_user, app_login_failure CASCADE")
    connection.commit()
    yield connection
    connection.execute("TRUNCATE app_user, app_login_failure CASCADE")
    connection.commit()
    connection.close()


def run(argv, password=PASSWORD):
    from scripts.create_user import main
    return main(argv, read_password=lambda: password)


def test_cli_creates_a_user_and_never_prints_the_password(db, capsys):
    assert run(["--login-id", "Alice"]) == 0
    output = capsys.readouterr()
    assert PASSWORD not in output.out + output.err
    assert db.execute("SELECT login_id, role FROM app_user").fetchone() == ("alice", "user")


def test_cli_can_create_an_admin(db):
    assert run(["--login-id", "boss", "--role", "admin"]) == 0
    assert db.execute("SELECT role FROM app_user WHERE login_id='boss'").fetchone() == ("admin",)


def test_cli_reports_duplicates_and_weak_passwords_without_a_traceback(db, capsys):
    assert run(["--login-id", "alice"]) == 0
    assert run(["--login-id", "ALICE"]) == 1
    assert run(["--login-id", "bob"], password="short") == 1
    err = capsys.readouterr().err
    assert "이미 사용 중" in err and "12자" in err and "Traceback" not in err


def test_cli_has_no_password_argument():
    from scripts.create_user import build_parser
    assert not any("password" in option for action in build_parser()._actions for option in action.option_strings)

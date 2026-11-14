"""Stage 1: DB-backed users and server sessions. Needs an isolated *_test database."""
import hashlib
import os

import psycopg
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict


DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="isolated TEST_DATABASE_URL not configured")
PASSWORD = "correct-horse-battery"
ORIGIN = {"Origin": "http://testserver"}


@pytest.fixture
def db(monkeypatch, service_schema):
    from db_safety import require_disposable_test_database
    require_disposable_test_database(DATABASE_URL)
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.delenv("APP_COOKIE_SECURE", raising=False)
    connection = psycopg.connect(DATABASE_URL)
    connection.execute("TRUNCATE app_user, app_login_failure CASCADE")
    connection.commit()
    yield connection
    connection.rollback()
    connection.execute("TRUNCATE app_user, app_login_failure CASCADE")
    connection.commit()
    connection.close()


@pytest.fixture
def client(db):
    from app.main import app
    return TestClient(app)


def make_user(db, login_id="alice", password=PASSWORD, role="user"):
    from app.auth.service import create_user
    user = create_user(db, login_id, password, role=role)
    db.commit()
    return user


def login(client, login_id="alice", password=PASSWORD, headers=ORIGIN):
    return client.post("/api/v1/auth/login", json={"login_id": login_id, "password": password}, headers=headers)


def test_anonymous_me_is_open_and_reports_unauthenticated(client):
    body = client.get("/api/v1/auth/me").json()
    assert body == {"authenticated": False, "user": None, "csrf_token": None}


def test_login_sets_httponly_session_cookie_and_returns_csrf_token(client, db):
    make_user(db)
    response = login(client)
    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is True
    assert body["user"] == {"id": body["user"]["id"], "login_id": "alice", "role": "user"}
    assert body["csrf_token"]
    assert "password" not in response.text and "hash" not in response.text
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    assert "secure" not in cookie.replace("samesite", "")
    assert client.get("/api/v1/auth/me").json()["user"]["login_id"] == "alice"


def test_cookie_is_secure_when_configured(client, db, monkeypatch):
    monkeypatch.setenv("APP_COOKIE_SECURE", "1")
    make_user(db)
    assert "secure" in login(client).headers["set-cookie"].lower().replace("samesite", "")


def test_passwords_are_argon2_hashed_and_tokens_are_stored_only_as_hashes(client, db):
    make_user(db)
    stored = db.execute("SELECT password_hash FROM app_user").fetchone()[0]
    assert stored.startswith("$argon2id$") and PASSWORD not in stored
    response = login(client)
    token = client.cookies.get("manual_session")
    assert token and token not in response.text
    (session_hash,) = db.execute("SELECT token_hash FROM app_session").fetchone()
    assert session_hash == hashlib.sha256(token.encode()).hexdigest()
    assert db.execute("SELECT count(*) FROM app_session WHERE token_hash=%s", (token,)).fetchone()[0] == 0


def test_unknown_user_and_wrong_password_are_indistinguishable(client, db):
    make_user(db)
    wrong = login(client, password="wrong-password-123")
    unknown = login(client, login_id="nobody")
    assert (wrong.status_code, wrong.json()) == (unknown.status_code, unknown.json()) == (
        401, {"detail": "아이디 또는 비밀번호가 올바르지 않습니다.", "code": "INVALID_CREDENTIALS"})
    assert "set-cookie" not in wrong.headers


def test_login_id_is_case_insensitive(client, db):
    make_user(db, "Alice")
    assert login(client, "ALICE").status_code == 200


def test_failed_logins_are_throttled_per_client_even_for_the_right_password(client, db):
    make_user(db)
    for _ in range(5):
        assert login(client, password="wrong-password-123").status_code == 401
    blocked = login(client)
    assert blocked.status_code == 429 and blocked.json()["code"] == "TOO_MANY_ATTEMPTS"


def test_failed_logins_are_throttled_per_account_across_clients(client, db):
    make_user(db)
    db.execute("INSERT INTO app_login_failure(login_id, client) SELECT 'alice', 'client-' || n FROM generate_series(1, 10) n")
    db.commit()
    assert login(client).status_code == 429


def test_unbounded_attacker_input_cannot_grow_the_failure_table(client, db):
    login(client, login_id="x" * 400)
    (stored,) = db.execute("SELECT login_id FROM app_login_failure").fetchone()
    assert len(stored) <= 64


def test_login_rotates_the_session(client, db):
    make_user(db)
    login(client)
    first = client.cookies.get("manual_session")
    login(client)
    second = client.cookies.get("manual_session")
    assert first != second
    assert db.execute("SELECT count(*) FROM app_session WHERE revoked_at IS NULL").fetchone()[0] == 1


def test_cross_origin_login_is_rejected(client, db):
    make_user(db)
    response = login(client, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403 and response.json()["code"] == "BAD_ORIGIN"
    assert "set-cookie" not in response.headers


def test_logout_requires_csrf_and_revokes_the_session(client, db):
    make_user(db)
    csrf = login(client).json()["csrf_token"]
    assert client.post("/api/v1/auth/logout", headers=ORIGIN).status_code == 403
    assert client.post("/api/v1/auth/logout", headers={**ORIGIN, "X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post("/api/v1/auth/logout", headers={**ORIGIN, "X-CSRF-Token": csrf}).status_code == 204
    assert client.get("/api/v1/auth/me").json()["authenticated"] is False
    assert db.execute("SELECT count(*) FROM app_session WHERE revoked_at IS NULL").fetchone()[0] == 0


def test_a_revoked_cookie_cannot_be_replayed(client, db):
    make_user(db)
    csrf = login(client).json()["csrf_token"]
    stolen = client.cookies.get("manual_session")
    client.post("/api/v1/auth/logout", headers={**ORIGIN, "X-CSRF-Token": csrf})
    replay = TestClient(client.app, cookies={"manual_session": stolen})
    assert replay.get("/api/v1/auth/me").json()["authenticated"] is False


def test_expired_sessions_and_deactivated_users_are_rejected(client, db):
    make_user(db)
    login(client)
    db.execute("UPDATE app_session SET expires_at = now() - interval '1 second'")
    db.commit()
    assert client.get("/api/v1/auth/me").json()["authenticated"] is False
    login(client)
    db.execute("UPDATE app_user SET is_active = FALSE")
    db.commit()
    assert client.get("/api/v1/auth/me").json()["authenticated"] is False
    assert login(client).status_code == 401


def test_protected_dependency_returns_login_required_then_enforces_csrf_for_writes(db):
    from app.auth.deps import require_csrf, require_user
    from app.auth.routes import install_auth

    app = FastAPI()
    install_auth(app)

    @app.get("/secret")
    def read(session=Depends(require_user)):
        return {"user": session.user.login_id}

    @app.post("/secret")
    def write(session=Depends(require_csrf)):
        return {"ok": True}

    make_user(db)
    anonymous = TestClient(app)
    assert anonymous.get("/secret").status_code == 401
    assert anonymous.get("/secret").json()["code"] == "LOGIN_REQUIRED"
    client = TestClient(app)
    csrf = login(client).json()["csrf_token"]
    assert client.get("/secret").json() == {"user": "alice"}
    assert client.post("/secret", headers=ORIGIN).status_code == 403
    assert client.post("/secret", headers={**ORIGIN, "X-CSRF-Token": csrf}).json() == {"ok": True}
    assert client.post("/secret", headers={"Origin": "https://evil.example", "X-CSRF-Token": csrf}).status_code == 403


def test_create_user_validates_login_id_password_and_uniqueness(db):
    from app.auth.service import DuplicateUser, InvalidLoginId, WeakPassword, create_user

    create_user(db, "Alice", PASSWORD)
    db.commit()
    with pytest.raises(DuplicateUser):
        create_user(db, "alice", PASSWORD)
    db.rollback()
    with pytest.raises(WeakPassword):
        create_user(db, "bob", "short")
    with pytest.raises(WeakPassword):
        create_user(db, "bob", "bob")  # not allowed to equal the login id
    with pytest.raises(InvalidLoginId):
        create_user(db, "bad id!", PASSWORD)
    with pytest.raises(ValueError):
        create_user(db, "carol", PASSWORD, role="superuser")

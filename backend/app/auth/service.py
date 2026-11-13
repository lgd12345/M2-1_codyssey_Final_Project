"""User, password and session rules. Takes an open psycopg connection; callers own the transaction."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import secrets
import unicodedata
from uuid import UUID

import psycopg
from email_validator import EmailNotValidError, validate_email
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256
SESSION_INTERVAL = "7 days"
THROTTLE_INTERVAL = "10 minutes"
MAX_FAILURES_PER_CLIENT = 5
MAX_FAILURES_PER_LOGIN = 10
ROLES = ("admin", "user", "customer")

_LOGIN_ID = re.compile(r"^[a-z0-9._@-]{3,64}$")
_HASHER = PasswordHash((Argon2Hasher(),))
_dummy_hash: str | None = None


class AuthError(Exception):
    status_code = 400
    code = "AUTH_ERROR"
    message = "요청을 처리할 수 없습니다."

    def __init__(self, message: str | None = None):
        super().__init__(message or self.message)
        self.message = message or self.message


class InvalidCredentials(AuthError):
    status_code, code = 401, "INVALID_CREDENTIALS"
    message = "아이디 또는 비밀번호가 올바르지 않습니다."


class TooManyAttempts(AuthError):
    status_code, code = 429, "TOO_MANY_ATTEMPTS"
    message = "로그인 시도가 너무 많습니다. 10분 뒤 다시 시도하세요."


class LoginRequired(AuthError):
    status_code, code = 401, "LOGIN_REQUIRED"
    message = "로그인이 필요합니다."


class BadOrigin(AuthError):
    status_code, code = 403, "BAD_ORIGIN"
    message = "허용되지 않은 요청 출처입니다."


class BadCsrf(AuthError):
    status_code, code = 403, "BAD_CSRF"
    message = "요청을 확인할 수 없습니다. 페이지를 새로고침한 뒤 다시 시도하세요."


class InvalidLoginId(AuthError):
    code = "INVALID_LOGIN_ID"
    message = "아이디는 3~64자의 영문 소문자·숫자와 . _ @ - 만 사용할 수 있습니다."


class WeakPassword(AuthError):
    code = "WEAK_PASSWORD"
    message = f"비밀번호는 {MIN_PASSWORD_LENGTH}자 이상이어야 하며 아이디와 같을 수 없습니다."


class DuplicateUser(AuthError):
    status_code, code = 409, "DUPLICATE_USER"
    message = "이미 사용 중인 아이디입니다."


@dataclass(frozen=True)
class AuthUser:
    id: UUID
    login_id: str
    role: str

    def public(self) -> dict[str, str]:
        return {"id": str(self.id), "login_id": self.login_id, "role": self.role}


@dataclass(frozen=True)
class SessionInfo:
    user: AuthUser
    csrf_token: str


def normalize_login_id(value: str) -> str:
    value = (value or '').strip()
    # IDNA must run before Unicode casefold (e.g. faß.de != fass.de).
    return _email_login(value) or unicodedata.normalize("NFKC", value).casefold()


def _email_login(value: str) -> str | None:
    try:
        return validate_email(value, check_deliverability=False, allow_smtputf8=False).ascii_email.casefold()
    except EmailNotValidError:
        return None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _dummy() -> str:
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _HASHER.hash(secrets.token_urlsafe(16))
    return _dummy_hash


def create_user(connection, login_id: str, password: str, *, role: str = "user") -> AuthUser:
    if role not in ROLES:
        raise ValueError("unsupported account role")
    normalized = normalize_login_id(login_id)
    if (role == 'customer' and not _email_login(normalized)) or (role != 'customer' and not _LOGIN_ID.fullmatch(normalized)):
        raise InvalidLoginId()
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH or password.casefold() == normalized:
        raise WeakPassword()
    try:
        with connection.transaction():
            row = connection.execute(
                "INSERT INTO app_user(login_id, password_hash, role) VALUES (%s,%s,%s) RETURNING id",
                (normalized, _HASHER.hash(password), role),
            ).fetchone()
    except psycopg.errors.UniqueViolation:
        raise DuplicateUser() from None
    return AuthUser(row[0], normalized, role)


def _failure_key(login_id: str) -> str:
    normalized = normalize_login_id(login_id)
    if _LOGIN_ID.fullmatch(normalized):
        return normalized
    # Preserve the existing <=64 character failure table without truncating long
    # email identities into the same throttle bucket. No email/DNS network lookup.
    return 'e:' + hashlib.sha256(normalized.encode()).hexdigest()[:62] if _email_login(normalized) else '?'


def authenticate(connection, login_id: str, password: str, client: str) -> AuthUser:
    """Verify credentials, recording failures. Always spends one password verification."""
    client = client[:64]
    key = _failure_key(login_id)
    connection.execute(f"DELETE FROM app_login_failure WHERE failed_at < now() - interval '{THROTTLE_INTERVAL}'")
    per_client = connection.execute(
        f"SELECT count(*) FROM app_login_failure WHERE client=%s AND failed_at >= now() - interval '{THROTTLE_INTERVAL}'",
        (client,)).fetchone()[0]
    per_login = connection.execute(
        f"SELECT count(*) FROM app_login_failure WHERE login_id=%s AND failed_at >= now() - interval '{THROTTLE_INTERVAL}'",
        (key,)).fetchone()[0] if key != "?" else 0
    if per_client >= MAX_FAILURES_PER_CLIENT or per_login >= MAX_FAILURES_PER_LOGIN:
        raise TooManyAttempts()
    row = connection.execute(
        "SELECT id, login_id, role, password_hash, is_active FROM app_user WHERE login_id=%s",
        (normalize_login_id(login_id),)).fetchone() if key != "?" else None
    stored = row[3] if row else _dummy()
    valid = _HASHER.verify(password[:MAX_PASSWORD_LENGTH], stored)
    if not (row and valid and len(password) <= MAX_PASSWORD_LENGTH and row[4]):
        connection.execute("INSERT INTO app_login_failure(login_id, client) VALUES (%s,%s)", (key, client))
        raise InvalidCredentials()
    connection.execute("UPDATE app_user SET last_login_at = now() WHERE id=%s", (row[0],))
    return AuthUser(row[0], row[1], row[2])


def create_session(connection, user_id: UUID, *, replacing: str | None = None) -> tuple[str, str]:
    """Issue a new session; any session being replaced is revoked (no session fixation)."""
    if replacing:
        revoke_session(connection, replacing)
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    connection.execute(
        f"INSERT INTO app_session(token_hash, user_id, csrf_token, expires_at) "
        f"VALUES (%s,%s,%s, now() + interval '{SESSION_INTERVAL}')",
        (_token_hash(token), user_id, csrf))
    return token, csrf


def get_session(connection, token: str | None) -> SessionInfo | None:
    if not token or len(token) > 200:
        return None
    row = connection.execute(
        """SELECT u.id, u.login_id, u.role, s.csrf_token
           FROM app_session s JOIN app_user u ON u.id = s.user_id
           WHERE s.token_hash=%s AND s.revoked_at IS NULL AND s.expires_at > now() AND u.is_active""",
        (_token_hash(token),)).fetchone()
    return SessionInfo(AuthUser(row[0], row[1], row[2]), row[3]) if row else None


def revoke_session(connection, token: str | None) -> None:
    if token:
        connection.execute("UPDATE app_session SET revoked_at = now() WHERE token_hash=%s AND revoked_at IS NULL",
                           (_token_hash(token),))


def csrf_matches(expected: str, supplied: str | None) -> bool:
    return bool(supplied) and secrets.compare_digest(expected.encode(), supplied.encode())

"""Request-level authentication, CSRF and origin checks."""
from __future__ import annotations

from contextlib import contextmanager
import os
from urllib.parse import urlsplit

import psycopg
from fastapi import Depends, Header, Request

from app.config import application_database_url
from app.auth.service import (
    AuthError, BadCsrf, BadOrigin, LoginRequired, SessionInfo, csrf_matches, get_session,
)

COOKIE_NAME = "manual_session"


def database_url() -> str:
    url = application_database_url()
    if not url:
        raise RuntimeError("RAG_DATABASE_URL or DATABASE_URL must be configured")
    return url


@contextmanager
def database():
    """One short transaction: committed on success, rolled back on any exception."""
    with psycopg.connect(database_url(), connect_timeout=5) as connection:
        yield connection


def cookie_secure() -> bool:
    return os.getenv("APP_COOKIE_SECURE") == "1"


def check_origin(request: Request) -> None:
    """Browsers send Origin on cross-site writes; reject any that is not this host."""
    origin = request.headers.get("origin")
    if origin is not None and urlsplit(origin).netloc != request.headers.get("host"):
        raise BadOrigin()


def current_session(request: Request) -> SessionInfo | None:
    with database() as connection:
        return get_session(connection, request.cookies.get(COOKIE_NAME))


def require_user(request: Request) -> SessionInfo:
    session = current_session(request)
    if session is None:
        raise LoginRequired()
    return session


def require_csrf(request: Request, x_csrf_token: str | None = Header(default=None)) -> SessionInfo:
    """For state-changing routes: same-origin, logged in, and the CSRF header must match."""
    check_origin(request)
    session = require_user(request)
    if not csrf_matches(session.csrf_token, x_csrf_token):
        raise BadCsrf()
    return session


class OperatorRequired(AuthError):
    status_code, code = 403, 'OPERATOR_REQUIRED'
    message = '운영진만 이용할 수 있는 기능입니다.'


def require_operator(session: SessionInfo = Depends(require_user)) -> SessionInfo:
    # Operators are admin accounts only. The user role is a customer account and must never reach
    # the agent/LLM or the operator APIs (cost and data protection for the public deployment).
    if session.user.role != 'admin':
        raise OperatorRequired()
    return session


def require_operator_csrf(session: SessionInfo = Depends(require_csrf)) -> SessionInfo:
    return require_operator(session)

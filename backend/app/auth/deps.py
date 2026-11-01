"""Request-level authentication, CSRF and origin checks."""
from __future__ import annotations

from contextlib import contextmanager
import os
from urllib.parse import urlsplit

import psycopg
from fastapi import Header, Request

from app.auth.service import (
    BadCsrf, BadOrigin, LoginRequired, SessionInfo, csrf_matches, get_session,
)

COOKIE_NAME = "manual_session"


def database_url() -> str:
    url = (os.getenv("RAG_DATABASE_URL", "") or os.getenv("DATABASE_URL", "")).strip()
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

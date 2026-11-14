"""Which database the application uses: DATABASE_URL, and nothing else.

TEST_DATABASE_URL is never an application database: it belongs to the regression runner and the ingestion scripts.
RAG_DATABASE_URL was retired. It used to win over DATABASE_URL, so a leftover value that differs would silently change
the database; startup therefore refuses it instead of ignoring it.
Startup notes name databases by name only, never host, user or password.
"""
from __future__ import annotations

import os
from typing import Mapping
from urllib.parse import urlsplit


def application_database_url(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    return env.get('DATABASE_URL', '').strip()


def _name(url: str) -> str:
    return urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1]


def check_configuration(env: Mapping[str, str] | None = None) -> None:
    """Raise when the retired RAG_DATABASE_URL still points somewhere other than DATABASE_URL."""
    env = os.environ if env is None else env
    legacy = env.get('RAG_DATABASE_URL', '').strip()
    if legacy and legacy != env.get('DATABASE_URL', '').strip():
        raise RuntimeError('RAG_DATABASE_URL is no longer used and differs from DATABASE_URL; the application would '
                           'switch databases. Move its value into DATABASE_URL and delete RAG_DATABASE_URL.')


def startup_notes(env: Mapping[str, str] | None = None) -> list[tuple[str, str]]:
    """(level, message) pairs describing the configuration traps; no connection is made."""
    env = os.environ if env is None else env
    used = application_database_url(env)
    if not used:
        return [('warning', 'no application database is configured (set DATABASE_URL)')]
    notes = [('info', f'application database: {_name(used)} (DATABASE_URL)')]
    if env.get('RAG_DATABASE_URL', '').strip():
        notes.append(('warning', 'RAG_DATABASE_URL is no longer used; remove it from the environment'))
    test = env.get('TEST_DATABASE_URL', '').strip()
    if test and _name(test) == _name(used):
        notes.append(('warning', 'TEST_DATABASE_URL names the application database; regression tests refuse it '
                                 'and only scripts/test_isolated.py (a disposable database) may run them'))
    try:
        workers = int(env.get('WEB_CONCURRENCY', '').strip() or 1)
    except ValueError:
        workers = 1
    if workers > 1:
        notes.append(('warning', f'WEB_CONCURRENCY={workers}: analysis recovery assumes a single server process; '
                                 f'with several, one worker can mark another worker\'s running analysis as failed'))
    return notes

"""Which database the application uses, in one place.

RAG_DATABASE_URL wins over DATABASE_URL (it was introduced to point the app at a separately prepared database).
TEST_DATABASE_URL is never an application database: it belongs to the regression runner and the ingestion scripts.
Startup notes name databases by name only, never host, user or password.
"""
from __future__ import annotations

import os
from typing import Mapping
from urllib.parse import urlsplit


def application_database_url(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    return (env.get('RAG_DATABASE_URL', '').strip() or env.get('DATABASE_URL', '').strip())


def _name(url: str) -> str:
    return urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1]


def startup_notes(env: Mapping[str, str] | None = None) -> list[tuple[str, str]]:
    """(level, message) pairs describing the configuration traps; no connection is made."""
    env = os.environ if env is None else env
    rag, base, test = (env.get(key, '').strip() for key in ('RAG_DATABASE_URL', 'DATABASE_URL', 'TEST_DATABASE_URL'))
    used = rag or base
    if not used:
        return [('warning', 'no application database is configured (set RAG_DATABASE_URL or DATABASE_URL)')]
    notes = [('info', f"application database: {_name(used)} ({'RAG_DATABASE_URL' if rag else 'DATABASE_URL'})")]
    if rag and base and _name(rag) != _name(base):
        notes.append(('info', f'DATABASE_URL ({_name(base)}) is ignored while RAG_DATABASE_URL is set; '
                              f'its schema may be older than the application database'))
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

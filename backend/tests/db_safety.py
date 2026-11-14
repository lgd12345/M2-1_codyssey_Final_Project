"""Keep destructive regression tests away from databases an application uses.

A database whose name merely ends in "_test" is not safe: the application database of a local setup can
have such a name. Only databases created by scripts/test_isolated.py (rag_regression_<hex>_test) qualify.
"""
from __future__ import annotations

import re
from typing import MutableMapping
from psycopg.conninfo import conninfo_to_dict

DISPOSABLE = re.compile(r'rag_regression_[a-z0-9]+_test')


def is_disposable_test_database(url: str) -> bool:
    try:  # accepts both postgresql:// URLs and the key=value form the runner produces
        name = conninfo_to_dict(url).get('dbname', '') if url else ''
    except Exception:
        return False
    return bool(DISPOSABLE.fullmatch(name or ''))


def guard_test_database(environment: MutableMapping[str, str]) -> str:
    """Drop a non-disposable TEST_DATABASE_URL so database tests skip. Returns a warning (no names) or ''."""
    url = environment.get('TEST_DATABASE_URL', '')
    if not url or is_disposable_test_database(url):
        return ''
    # Empty, not deleted: application modules call load_dotenv(override=False) on import and would restore it.
    environment['TEST_DATABASE_URL'] = ''
    return ('TEST_DATABASE_URL is not a disposable database created by scripts/test_isolated.py; database tests are '
            'skipped so that regression tests cannot truncate an application database.')


def require_disposable_test_database(url: str) -> None:
    """Defence in depth for fixtures that TRUNCATE: refuse anything but a runner-created database."""
    if not is_disposable_test_database(url):
        raise RuntimeError('refusing to run destructive tests: the database is not a disposable one created by '
                           'scripts/test_isolated.py')

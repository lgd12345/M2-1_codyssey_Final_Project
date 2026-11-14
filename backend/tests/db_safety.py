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


def assign_worker_database(environment: MutableMapping[str, str]) -> None:
    """Point this test process at ITS disposable database.

    The runner creates one rag_regression_<hex>_test database per worker and lists them in REGRESSION_DATABASES (JSON).
    Parallel workers must never share a database: the tests TRUNCATE tables. Without that variable (not started by the
    runner) nothing is changed here, and guard_test_database still decides whether database tests may run at all.
    """
    import json
    import os

    raw = environment.get('REGRESSION_DATABASES', '')
    if not raw:
        return
    try:
        urls = json.loads(raw)
    except ValueError:
        raise RuntimeError('REGRESSION_DATABASES is not valid JSON') from None
    if not isinstance(urls, list) or not urls or not all(isinstance(u, str) and is_disposable_test_database(u) for u in urls):
        raise RuntimeError('REGRESSION_DATABASES must list only disposable databases created by scripts/test_isolated.py')
    worker = environment.get('PYTEST_XDIST_WORKER', 'gw0')
    index = int(worker[2:]) if re.fullmatch(r'gw\d+', worker) else 0
    if index >= len(urls):
        raise RuntimeError('more workers than disposable databases')
    environment['TEST_DATABASE_URL'] = urls[index]
    environment['DATABASE_URL'] = urls[index]  # the application under test uses the same disposable database

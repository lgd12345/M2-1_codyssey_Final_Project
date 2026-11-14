from pathlib import Path
import os
import warnings

from dotenv import load_dotenv

from db_safety import assign_worker_database, guard_test_database

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
# Must run before test modules read TEST_DATABASE_URL at import time.
assign_worker_database(os.environ)  # parallel runs: each worker has its own disposable database
_warning = guard_test_database(os.environ)
if _warning:
    warnings.warn(_warning)

# Argon2 with library defaults costs ~60 ms per hash or check, and every database test creates and signs in several
# users. The tests use the cheapest valid parameters; the application keeps the defaults (guarded in test_isolated_runner).
import app.auth.service as _auth_service  # noqa: E402
from pwdlib import PasswordHash  # noqa: E402
from pwdlib.hashers.argon2 import Argon2Hasher  # noqa: E402

_auth_service._HASHER = PasswordHash((Argon2Hasher(time_cost=1, memory_cost=8, parallelism=1),))

import pytest  # noqa: E402


@pytest.fixture(scope='session')
def service_schema():
    """Once per worker, not 16 migration checks for every intake/auth fixture."""
    from scripts.migrate import apply_migrations
    url = os.getenv('TEST_DATABASE_URL', '')
    if not url:
        pytest.skip('isolated TEST_DATABASE_URL not configured')
    apply_migrations(url)


def pytest_collection_modifyitems(items):
    # xdist initially assigns TWO consecutive items to each worker. Pair each browser shard
    # with a short test, or the first worker receives multiple long browser jobs.
    browser = [item for item in items if 'test_service_requests_e2e.py::' in item.nodeid]
    other = [item for item in items if 'test_service_requests_e2e.py::' not in item.nodeid]
    paired = []
    for index, item in enumerate(browser):
        paired.append(item)
        if index < len(other):
            paired.append(other[index])
    items[:] = paired + other[len(browser):]

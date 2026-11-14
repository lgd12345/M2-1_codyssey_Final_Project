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

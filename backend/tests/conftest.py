from pathlib import Path
import os
import warnings

from dotenv import load_dotenv

from db_safety import guard_test_database

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
# Must run before test modules read TEST_DATABASE_URL at import time.
_warning = guard_test_database(os.environ)
if _warning:
    warnings.warn(_warning)

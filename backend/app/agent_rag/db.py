from __future__ import annotations

import os
from functools import partial
from typing import Any


def connect_database(database_url: str | None = None):
    import psycopg

    url = (database_url or os.getenv("DATABASE_URL", "")).strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(url, connect_timeout=5)


def pgvector_literal(values: list[float]) -> str:
    return "[" + ",".join(format(float(value), ".9g") for value in values) + "]"

from __future__ import annotations

from functools import partial
from typing import Any

from app.config import application_database_url


def connect_database(database_url: str | None = None):
    import psycopg

    url = (database_url or application_database_url()).strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(url, connect_timeout=5)


def pgvector_literal(values: list[float]) -> str:
    return "[" + ",".join(format(float(value), ".9g") for value in values) + "]"

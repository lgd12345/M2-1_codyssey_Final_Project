import asyncio

import psycopg
import pytest

from app.main import app
from scripts.migrate import MIGRATIONS, apply_migrations


def test_app_startup_never_connects_or_creates_schema(monkeypatch):
    def unexpected_connect(*_args, **_kwargs):
        raise AssertionError("startup must not connect to the database")

    monkeypatch.setattr("psycopg.connect", unexpected_connect)

    async def run_lifespan():
        async with app.router.lifespan_context(app):
            return "started"

    assert asyncio.run(run_lifespan()) == "started"


@pytest.mark.skipif(not __import__("os").getenv("TEST_DATABASE_URL"), reason="isolated TEST_DATABASE_URL not configured")
def test_migration_is_idempotent_and_creates_rag_tables():
    import os
    url = os.environ["TEST_DATABASE_URL"]
    first = apply_migrations(url)
    second = apply_migrations(url)
    assert set(first).issubset({path.stem for path in MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql")})
    with psycopg.connect(url) as connection:
        applied = {row[0] for row in connection.execute("SELECT version FROM rag_schema_migration")}
    assert {path.stem for path in MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql")} <= applied
    assert second == []
    with psycopg.connect(url) as connection:
        assert connection.execute("""SELECT count(*) FROM information_schema.columns
                                     WHERE table_name='rag_document' AND column_name='document_kind'""").fetchone()[0] == 0

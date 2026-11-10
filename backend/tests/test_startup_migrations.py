import asyncio

import pytest

from app.main import app
from scripts.migrate import apply_migrations


def test_app_startup_never_connects_or_creates_schema(monkeypatch):
    def unexpected_connect(*_args, **_kwargs):
        raise AssertionError("startup must not connect to the database")

    monkeypatch.setattr("app.main.psycopg.connect", unexpected_connect)

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
    assert set(first).issubset({"001_agent_rag", "002_embedding_endpoint_identity", "003_auth",
                                   "004_agent_runs", "005_conversation",
                                   "006_conversational_status", "007_drop_document_kind",
                                   "008_rag_case", "009_agent_run_case_citations"})
    assert second == []
    import psycopg
    with psycopg.connect(url) as connection:
        assert connection.execute("""SELECT count(*) FROM information_schema.columns
                                     WHERE table_name='rag_document' AND column_name='document_kind'""").fetchone()[0] == 0

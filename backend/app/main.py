import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

SCHEMA_STATEMENTS = (
    "CREATE EXTENSION IF NOT EXISTS vector",
    """
    CREATE TABLE IF NOT EXISTS knowledge_documents (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        title TEXT NOT NULL,
        source_uri TEXT,
        content TEXT NOT NULL,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        embedding vector(1536),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS knowledge_documents_embedding_hnsw_idx
        ON knowledge_documents USING hnsw (embedding vector_cosine_ops)
        WHERE embedding IS NOT NULL
    """,
)


def initialize_database(database_url: str) -> None:
    """Create the pgvector schema idempotently when the database is reachable."""
    with psycopg.connect(database_url, connect_timeout=3) as connection:
        with connection.cursor() as cursor:
            for statement in SCHEMA_STATEMENTS:
                cursor.execute(statement)
    logger.info("Database schema is ready")


async def retry_database_initialization(database_url: str) -> None:
    delay = 2
    while True:
        await asyncio.sleep(delay)
        try:
            await asyncio.to_thread(initialize_database, database_url)
            return
        except psycopg.Error:
            logger.exception("Database initialization failed; retrying in %s seconds", delay)
            delay = min(delay * 2, 30)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    database_url = os.getenv("DATABASE_URL")
    retry_task = None
    if database_url:
        try:
            await asyncio.to_thread(initialize_database, database_url)
        except psycopg.Error:
            logger.exception("Database initialization failed; API will start and retry in the background")
            retry_task = asyncio.create_task(retry_database_initialization(database_url))
    else:
        logger.info("DATABASE_URL is not set; skipping database initialization")
    try:
        yield
    finally:
        if retry_task:
            retry_task.cancel()
            with suppress(asyncio.CancelledError):
                await retry_task


app = FastAPI(title="Service Desk PoC API", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/db-status")
def db_status() -> dict[str, str | bool]:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")
    try:
        with psycopg.connect(database_url, connect_timeout=3) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
                vector_enabled = cursor.fetchone()[0]
        return {"status": "ok", "vector_enabled": vector_enabled}
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


static_dir = Path(os.getenv("STATIC_DIR", Path(__file__).resolve().parent.parent / "static"))
if static_dir.is_dir():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
else:
    logger.info("Static directory %s does not exist; frontend mount skipped", static_dir)

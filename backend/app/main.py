import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from app.auth.routes import install_auth
from app.documents.routes import router as documents_router
from app.db_inspection import router as db_inspection_router
from app.runs.routes import router as runs_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Database schema changes are explicit migrations; app startup is read-only.
    yield


app = FastAPI(title="Service Desk Agent API", lifespan=lifespan)
install_auth(app)
app.include_router(runs_router)
app.include_router(documents_router)
app.include_router(db_inspection_router)


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

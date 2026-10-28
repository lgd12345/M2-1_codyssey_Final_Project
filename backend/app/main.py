import os

import psycopg
from fastapi import FastAPI, HTTPException

app = FastAPI(title="Service Desk PoC API")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/db-status")
def db_status() -> dict[str, str | bool]:
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=3) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
                vector_enabled = cursor.fetchone()[0]
        return {"status": "ok", "vector_enabled": vector_enabled}
    except (psycopg.Error, KeyError) as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

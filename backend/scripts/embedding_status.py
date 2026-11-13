"""Read-only check that runtime embedding provider and active DB index agree. No remote calls, no writes."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)
sys.path.insert(0, str(ROOT))

from app.agent_rag.embedding import configured_embedder
from app.agent_rag.embedding_readiness import embedding_readiness


def connect_for_status():
    # Same database selection as the running app (RAG_DATABASE_URL first).
    url = (os.getenv("RAG_DATABASE_URL", "") or os.getenv("DATABASE_URL", "")).strip()
    if not url:
        raise ValueError("RAG_DATABASE_URL or DATABASE_URL is not configured")
    connection = psycopg.connect(url, connect_timeout=5)
    connection.execute("SET TRANSACTION READ ONLY")
    return connection


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("gemini", "qwen"), default=None,
                        help="runtime provider to check (default: RAG_EMBEDDING_PROVIDER, else gemini)")
    args = parser.parse_args(argv)
    try:
        embedder = configured_embedder(provider=args.provider)
        connection = connect_for_status()
    except Exception as exc:  # never print DSNs or keys
        print(json.dumps({"status": "unavailable", "error": type(exc).__name__}))
        return 2
    try:
        report = embedding_readiness(connection, embedder)
        report["database"] = connection.execute("SELECT current_database()").fetchone()[0]
        report["provider"] = args.provider or os.getenv("RAG_EMBEDDING_PROVIDER", "gemini")
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["status"] == "ready" else 1
    finally:
        connection.rollback()
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())

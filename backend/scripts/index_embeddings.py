from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)
sys.path.insert(0, str(ROOT))

from app.agent_rag.embedding import configured_embedder
from app.agent_rag.embedding_events import record_embedding_error
from app.agent_rag.embedding_index import ensure_embedding_config, index_embeddings


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate resumable embedding vectors for ingested manual pages.")
    parser.add_argument("--database-url-env", default="TEST_DATABASE_URL",
                        choices=("TEST_DATABASE_URL", "DATABASE_URL"))
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--limit", type=int, default=None,
                        help="embed at most this many contents in this run (probe); run again to resume the rest")
    parser.add_argument("--provider", choices=("gemini", "qwen"), default=None,
                        help="embedding model to index with (default: RAG_EMBEDDING_PROVIDER, else qwen)")
    parser.add_argument("--only", choices=("all", "pages", "cases"), default="all",
                        help="restrict to manual pages or past service cases (default: both)")
    parser.add_argument("--activate", action="store_true", help="activate only after every eligible page is embedded")
    args = parser.parse_args()
    database_url = os.getenv(args.database_url_env, "").strip()
    if not database_url:
        parser.error(f"{args.database_url_env} is not configured")
    db_name = urlsplit(database_url).path.rstrip("/").split("/")[-1]
    if args.database_url_env == "TEST_DATABASE_URL" and not db_name.endswith("_test"):
        parser.error("TEST_DATABASE_URL must point to a database ending in _test")
    embedder = configured_embedder(
        provider=args.provider, error_sink=lambda event: record_embedding_error(event, database_url=database_url)
    )
    with psycopg.connect(database_url, connect_timeout=5) as connection:
        result = index_embeddings(connection, embedder, batch_size=args.batch_size, limit=args.limit,
                                  only=args.only)
        if args.activate:
            if result["remaining"]:
                parser.error("cannot activate: failed or pending embeddings remain")
            ensure_embedding_config(connection, embedder, activate=True)
    print(f"{embedder.PROVIDER} embedding run: completed={result['completed']} failed={result['failed']} "
          f"remaining={result['remaining']} config={result['config_id']}")
    return 2 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

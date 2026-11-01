from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)
sys.path.insert(0, str(ROOT))

from app.agent_rag.ingest import ingest_corpus


def main() -> int:
    parser = argparse.ArgumentParser(description="Idempotently ingest a prepared manual corpus.")
    parser.add_argument("--corpus", default=os.getenv("RAG_CORPUS_DIR", str(ROOT / "data/test_corpus")))
    parser.add_argument("--database-url-env", default="TEST_DATABASE_URL",
                        choices=("TEST_DATABASE_URL", "DATABASE_URL"))
    args = parser.parse_args()
    database_url = os.getenv(args.database_url_env, "").strip()
    if not database_url:
        parser.error(f"{args.database_url_env} is not configured")
    db_name = urlsplit(database_url).path.rstrip("/").split("/")[-1]
    if args.database_url_env == "TEST_DATABASE_URL" and not db_name.endswith("_test"):
        parser.error("TEST_DATABASE_URL must point to a database ending in _test")
    summary = ingest_corpus(args.corpus, database_url=database_url)
    print(f"Ingested {summary.documents} documents, {summary.pages} pages, "
          f"{summary.identifiers} exact identifiers, {summary.links} page links.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

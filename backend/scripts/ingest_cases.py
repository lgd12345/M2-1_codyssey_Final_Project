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

from app.agent_rag.cases import ingest_cases, load_cases


def main() -> int:
    parser = argparse.ArgumentParser(description="Idempotently ingest the past service case (FSR) CSV.")
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--database-url-env", default="TEST_DATABASE_URL",
                        choices=("TEST_DATABASE_URL", "DATABASE_URL"))
    parser.add_argument("--dry-run", action="store_true", help="parse and report only; do not write")
    args = parser.parse_args()
    records, stats = load_cases(args.csv)
    print(f"rows={stats.rows} kept={stats.kept} quality={stats.by_quality} no_resolution={stats.no_resolution} "
          f"short_resolution={stats.short_resolution} same_as_complaint={stats.same_as_complaint} "
          f"duplicates_merged={stats.duplicates_merged}")
    if args.dry_run:
        return 0
    database_url = os.getenv(args.database_url_env, "").strip()
    if not database_url:
        parser.error(f"{args.database_url_env} is not configured")
    db_name = urlsplit(database_url).path.rstrip("/").split("/")[-1]
    if args.database_url_env == "TEST_DATABASE_URL" and not db_name.endswith("_test"):
        parser.error("TEST_DATABASE_URL must point to a database ending in _test")
    print(f"Ingested {ingest_cases(records, database_url=database_url)} cases.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

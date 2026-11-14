from __future__ import annotations

import argparse
import os
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)
MIGRATIONS = ROOT / "migrations"


def apply_migrations(database_url: str, *, migrations_dir: str | Path = MIGRATIONS) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(database_url, connect_timeout=5) as connection:
        with connection.transaction():
            connection.execute("""
                CREATE TABLE IF NOT EXISTS rag_schema_migration (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
        for migration_path in sorted(Path(migrations_dir).glob("[0-9][0-9][0-9]_*.sql")):
            version = migration_path.stem
            with connection.transaction():
                exists = connection.execute(
                    "SELECT 1 FROM rag_schema_migration WHERE version = %s", (version,)
                ).fetchone()
                if exists:
                    continue
                sql = migration_path.read_text(encoding="utf-8")
                connection.execute(sql, prepare=False)
                connection.execute("INSERT INTO rag_schema_migration(version) VALUES (%s)", (version,))
            applied.append(version)
    return applied


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply the manual-agent database migrations.")
    parser.add_argument("--env-name", choices=("TEST_DATABASE_URL", "DATABASE_URL"), default="TEST_DATABASE_URL")
    parser.add_argument("--allow-non-test", action="store_true",
                        help="required for DATABASE_URL (the database the running app uses); prevents accidental dev/prod migration")
    args = parser.parse_args()
    database_url = os.getenv(args.env_name, "").strip()
    if not database_url:
        parser.error(f"{args.env_name} is not configured")
    database_name = urlsplit(database_url).path.rstrip("/").split("/")[-1]
    if args.env_name == "TEST_DATABASE_URL" and not database_name.endswith("_test"):
        parser.error("TEST_DATABASE_URL must point to a database ending in _test")
    if args.env_name != "TEST_DATABASE_URL" and not args.allow_non_test:
        parser.error(f"refusing to migrate {args.env_name} without --allow-non-test")
    applied = apply_migrations(database_url)
    print("Applied: " + (", ".join(applied) if applied else "none; schema is current"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

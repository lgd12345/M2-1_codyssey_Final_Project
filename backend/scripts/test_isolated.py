"""Run regressions in a disposable DB; never truncate the configured corpus DB."""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import quote
from uuid import uuid4

from dotenv import dotenv_values, load_dotenv
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[1]


def regression_database_dsn(base: str, name: str) -> str:
    if not conninfo_to_dict(base).get("dbname", "").endswith("_test"):
        raise ValueError("TEST_DATABASE_URL must reference an isolated _test database")
    if not re.fullmatch(r"rag_regression_[a-z0-9]+_test", name):
        raise ValueError("refusing to use a non-disposable database name")
    return make_conninfo(base, dbname=name)


def redact_output(output: str, config: dict[str, str | None]) -> str:
    secrets: set[str] = set()
    for key, value in config.items():
        if not value:
            continue
        if any(word in key.upper() for word in ("KEY", "PASSWORD", "TOKEN", "DATABASE_URL")):
            secrets.add(value)
        if "DATABASE_URL" in key.upper():
            try:
                password = conninfo_to_dict(value).get("password", "")
                if password:
                    secrets.update((password, quote(password, safe="")))
            except psycopg.Error:
                pass
    for secret in sorted(secrets, key=len, reverse=True):
        output = output.replace(secret, "[REDACTED]")
    return output


def main() -> int:
    load_dotenv(ROOT / ".env", override=False)
    config = {**dotenv_values(ROOT / ".env"), **os.environ}
    base = os.getenv("TEST_DATABASE_URL", "").strip()
    if not base:
        print("TEST_DATABASE_URL is required; no application database fallback is allowed.")
        return 2
    name = "rag_regression_" + uuid4().hex[:16] + "_test"
    try:
        target = regression_database_dsn(base, name)
        with psycopg.connect(base, autocommit=True, connect_timeout=5) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            print("Created disposable regression database; existing corpus is not a test target.", flush=True)
            try:
                env = os.environ.copy()
                env["TEST_DATABASE_URL"] = target
                env["RAG_DATABASE_URL"] = target
                env["PYDANTIC_AI_NO_BANNER"] = "1"
                parent = ROOT / ".pytest-tmp"
                parent.mkdir(exist_ok=True)
                with tempfile.TemporaryDirectory(prefix="isolated-", dir=parent) as temporary:
                    args = sys.argv[1:] or ["tests", "-q", "--disable-warnings"]
                    result = subprocess.run(
                        [sys.executable, "-m", "pytest", *args, "--basetemp", str(Path(temporary) / "pytest")],
                        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                    )
                    print(redact_output(result.stdout + result.stderr, config), flush=True)
                    return result.returncode
            finally:
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
                print("Dropped disposable regression database.", flush=True)
    except Exception as exc:
        # Never emit exception messages or DSNs, even when the test environment is misconfigured.
        print(f"Isolated regression runner failed: {type(exc).__name__}", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

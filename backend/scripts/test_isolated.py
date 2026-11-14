"""Run regressions in a disposable DB; never truncate the configured corpus DB."""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import quote
import json
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


MAX_WORKERS = 32


def split_worker_option(arguments: list[str], *, default: int) -> tuple[int, list[str]]:
    """Take the runner's own --workers N out of the arguments that go to pytest."""
    rest, workers, index = [], default, 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--workers" or argument.startswith("--workers="):
            value = argument.partition("=")[2] if "=" in argument else (arguments[index + 1] if index + 1 < len(arguments) else "")
            index += 1 if "=" in argument else 2
            if not value.isdigit() or not 1 <= int(value) <= MAX_WORKERS:
                raise ValueError(f"--workers must be a number from 1 to {MAX_WORKERS}")
            workers = int(value)
            continue
        rest.append(argument)
        index += 1
    return workers, rest


def pytest_arguments(workers: int, arguments: list[str]) -> list[str]:
    if workers <= 1 or "-n" in arguments or any(a.startswith(("-n=", "--numprocesses")) for a in arguments):
        return arguments
    return ["-n", str(workers), "--maxschedchunk=2", *arguments]


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
    try:
        workers, pytest_args = split_worker_option(sys.argv[1:], default=int(os.getenv("TEST_WORKERS", "4")))
    except ValueError as exc:
        print(str(exc))
        return 2
    created: list[str] = []
    try:
        # One disposable database per worker: the tests TRUNCATE tables, so workers must never share one.
        with psycopg.connect(base, autocommit=True, connect_timeout=5) as admin:
            try:
                targets = []
                for _ in range(workers):
                    name = "rag_regression_" + uuid4().hex[:16] + "_test"
                    targets.append(regression_database_dsn(base, name))
                    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
                    created.append(name)
                print(f"Created {workers} disposable regression database(s); existing corpus is not a test target.", flush=True)
                env = os.environ.copy()
                env["TEST_DATABASE_URL"] = targets[0]
                env["DATABASE_URL"] = targets[0]  # the application inside the tests uses the disposable database
                env["REGRESSION_DATABASES"] = json.dumps(targets)
                env["PYDANTIC_AI_NO_BANNER"] = "1"
                parent = ROOT / ".pytest-tmp"
                parent.mkdir(exist_ok=True)
                with tempfile.TemporaryDirectory(prefix="isolated-", dir=parent) as temporary:
                    args = pytest_arguments(workers, pytest_args or ["tests", "-q", "--disable-warnings"])
                    result = subprocess.run(
                        [sys.executable, "-m", "pytest", *args, "--basetemp", str(Path(temporary) / "pytest")],
                        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                    )
                    print(redact_output(result.stdout + result.stderr, config), flush=True)
                    return result.returncode
            finally:
                for name in created:
                    admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
                print(f"Dropped {len(created)} disposable regression database(s).", flush=True)
    except Exception as exc:
        # Never emit exception messages or DSNs, even when the test environment is misconfigured.
        print(f"Isolated regression runner failed: {type(exc).__name__}", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

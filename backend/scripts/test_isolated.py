"""Run regressions in a disposable DB; never truncate the configured corpus DB."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
import time
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
DEFAULT_WORKERS = min(8, os.cpu_count() or 1)


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


def database_jobs(base: str, names: list[str], *, create: bool) -> None:
    """Independent CREATE/DROP operations, parallel connections; validate every name before any SQL."""
    for name in names:
        regression_database_dsn(base, name)

    def one(name):
        with psycopg.connect(base, autocommit=True, connect_timeout=5) as connection:
            statement = "CREATE DATABASE {}" if create else "DROP DATABASE IF EXISTS {} WITH (FORCE)"
            connection.execute(sql.SQL(statement).format(sql.Identifier(name)))

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(names)))) as pool:
        # All submitted jobs finish before cleanup, even when one raises.
        list(pool.map(one, names))


def main() -> int:
    load_dotenv(ROOT / ".env", override=False)
    config = {**dotenv_values(ROOT / ".env"), **os.environ}
    base = os.getenv("TEST_DATABASE_URL", "").strip()
    if not base:
        print("TEST_DATABASE_URL is required; no application database fallback is allowed.")
        return 2
    try:
        workers, pytest_args = split_worker_option(sys.argv[1:], default=int(os.getenv("TEST_WORKERS", str(DEFAULT_WORKERS))))
    except ValueError as exc:
        print(str(exc))
        return 2
    names = ["rag_regression_" + uuid4().hex[:16] + "_test" for _ in range(workers)]
    started = time.perf_counter()
    try:
        targets = [regression_database_dsn(base, name) for name in names]
        try:
            database_jobs(base, names, create=True)
            print(f"Created {workers} disposable databases in {time.perf_counter() - started:.2f}s; existing corpus is not a test target.", flush=True)
            env = os.environ.copy()
            env["TEST_DATABASE_URL"] = targets[0]
            env["DATABASE_URL"] = targets[0]
            env["REGRESSION_DATABASES"] = json.dumps(targets)
            env["TEST_WORKERS"] = str(workers)  # E2E shards track actual worker count
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
            # Names were generated by this invocation. IF EXISTS also covers partial CREATE failure.
            database_jobs(base, names, create=False)
            print(f"Dropped {len(names)} disposable databases. Total wall time: {time.perf_counter() - started:.2f}s.", flush=True)
    except Exception as exc:
        print(f"Isolated regression runner failed: {type(exc).__name__}", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

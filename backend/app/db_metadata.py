"""Bounded, read-only deployment metadata inspection without connection details."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row


_TARGETS = ("DATABASE_URL", "RAG_DATABASE_URL")
_TABLES = (
    "app_user", "app_session", "app_login_failure", "agent_run",
    "agent_run_asset", "rag_document", "rag_embedding_config", "rag_schema_migration",
)
_LIMIT = 100
_IDENTITY_LIMIT = (
    "Groups compare observed server endpoint and database/role values only; "
    "they do not prove cluster identity behind proxies or replicas. "
    "Unavailable endpoints are not equated across different DSNs. "
    "Privileges describe the current role, not migration authority or unrestricted row access."
)
_IDENTITY_SQL = """
    SELECT pg_catalog.current_database() AS database_name,
           current_role AS effective_role, session_user AS session_role,
           pg_catalog.inet_server_addr()::pg_catalog.text AS server_address,
           pg_catalog.inet_server_port() AS server_port,
           pg_catalog.current_schema() AS schema_name,
           pg_catalog.current_setting('server_version_num') AS server_version_num,
           pg_catalog.current_setting('transaction_read_only') AS read_only,
           pg_catalog.has_database_privilege(
               pg_catalog.current_database(), 'CONNECT') AS connect_privilege
"""
_SCHEMA_SQL = """
    SELECT pg_catalog.has_schema_privilege(oid, 'USAGE') AS usage,
           pg_catalog.has_schema_privilege(oid, 'CREATE') AS create
    FROM pg_catalog.pg_namespace WHERE nspname = %s
"""
_PRESENCE_SQL = """
    SELECT requested.name, EXISTS (
        SELECT 1 FROM pg_catalog.pg_class AS c
        WHERE c.relname = requested.name AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
    ) AS present
    FROM pg_catalog.unnest(%s::pg_catalog.text[]) AS requested(name)
"""
_TABLE_SQL = """
    SELECT c.relname AS name, n.nspname AS schema_name, c.relkind AS kind,
           pg_catalog.pg_table_is_visible(c.oid) AS visible,
           pg_catalog.has_schema_privilege(n.oid, 'USAGE') AS schema_usage,
           pg_catalog.has_table_privilege(c.oid, 'SELECT') AS select,
           pg_catalog.has_table_privilege(c.oid, 'INSERT') AS insert,
           pg_catalog.has_table_privilege(c.oid, 'UPDATE') AS update,
           pg_catalog.has_table_privilege(c.oid, 'DELETE') AS delete,
           pg_catalog.row_security_active(c.oid) AS rls
    FROM pg_catalog.pg_class AS c
    JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
    WHERE c.relname = ANY(%s::pg_catalog.text[]) AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
    ORDER BY c.relname, n.nspname, c.oid LIMIT 101
"""
_FLAGS = ("visible", "schema_usage", "select", "insert", "update", "delete", "rls")


@dataclass
class _Snapshot:
    report: dict[str, Any]
    endpoint: tuple[Any, ...] | None
    database: str
    effective_role: str
    session_role: str
    schemas: list[str]


class _ReadOnlyNotConfirmed(Exception):
    pass


def _boolean(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError("Invalid metadata boolean")
    return value


def _migrations(cursor: Any, tables: list[dict], truncated: bool) -> dict:
    result: dict[str, Any] = {"status": "not_found", "rows": [], "truncated": False}
    if truncated:
        result["status"] = "not_inspected_truncated"
        return result
    candidates = [row for row in tables if row["name"] == "rag_schema_migration" and row["visible"]]
    if not candidates:
        if any(row["name"] == "rag_schema_migration" for row in tables):
            result["status"] = "not_visible"
        return result
    if len(candidates) != 1:
        result["status"] = "ambiguous"
        return result
    table = candidates[0]
    if table["kind"] not in ("r", "p"):
        result["status"] = "unsupported_relation_kind"
        return result
    if not (table["schema_usage"] and table["select"]):
        result["status"] = "table_select_not_confirmed"
        return result
    cursor.execute(
        sql.SQL("SELECT version, applied_at FROM {} ORDER BY version LIMIT 101").format(
            sql.Identifier(table["schema_name"], "rag_schema_migration")
        )
    )
    rows = cursor.fetchmany(_LIMIT + 1)
    versions = []
    for row in rows[:_LIMIT]:
        version, applied_at = row["version"], row["applied_at"]
        if not isinstance(version, str) or not re.fullmatch(r"[0-9]{3}_[A-Za-z0-9_]{1,160}", version):
            raise ValueError("Invalid migration version metadata")
        if not isinstance(applied_at, datetime):
            raise ValueError("Invalid migration timestamp metadata")
        versions.append({"version": version, "applied_at": applied_at.isoformat()})
    return {"status": "ok", "rows": versions, "truncated": len(rows) > _LIMIT,
            "row_security_active": table["rls"]}


def _inspect(dsn: str, connect: Callable) -> _Snapshot | dict:
    phase = "connection_failed"
    try:
        with connect(dsn, connect_timeout=3, autocommit=True) as connection:
            phase = "metadata_failed"
            with connection.transaction():
                with connection.cursor(row_factory=dict_row) as cursor:
                    cursor.execute("SET TRANSACTION READ ONLY")
                    cursor.execute("SET LOCAL statement_timeout = '2s'")
                    cursor.execute("SET LOCAL lock_timeout = '500ms'")
                    cursor.execute(_IDENTITY_SQL)
                    identity = cursor.fetchone()
                    if identity is None or identity["read_only"] != "on":
                        raise _ReadOnlyNotConfirmed
                    schema_name = identity["schema_name"]
                    schema = {"present": False, "usage": False, "create": False}
                    if schema_name is not None:
                        cursor.execute(_SCHEMA_SQL, (schema_name,))
                        schema_row = cursor.fetchone()
                        if schema_row is not None:
                            schema = {"present": True, "usage": _boolean(schema_row["usage"]),
                                      "create": _boolean(schema_row["create"])}
                    cursor.execute(_PRESENCE_SQL, (list(_TABLES),))
                    presence_rows = cursor.fetchmany(len(_TABLES) + 1)
                    presence = {row["name"]: _boolean(row["present"]) for row in presence_rows}
                    if set(presence) != set(_TABLES) or len(presence_rows) != len(_TABLES):
                        raise ValueError("Invalid relation presence metadata")
                    cursor.execute(_TABLE_SQL, (list(_TABLES),))
                    rows = cursor.fetchmany(_LIMIT + 1)
                    truncated = len(rows) > _LIMIT
                    tables, schemas = [], []
                    for row in rows[:_LIMIT]:
                        if row["name"] not in _TABLES or row["kind"] not in ("r", "p", "v", "m", "f"):
                            raise ValueError("Invalid relation metadata")
                        table = {"name": row["name"], "kind": row["kind"]}
                        table.update({flag: _boolean(row[flag]) for flag in _FLAGS})
                        tables.append(table)
                        schemas.append(row["schema_name"])
                    phase = "migration_read_failed"
                    migrations = _migrations(cursor, rows[:_LIMIT], truncated)
                    phase = "metadata_failed"
                    report = {"status": "ok", "read_only": True,
                              "server_version_num": int(identity["server_version_num"]),
                              "connect_privilege": _boolean(identity["connect_privilege"]),
                              "current_schema": schema, "table_presence": presence,
                              "tables": tables, "tables_truncated": truncated,
                              "migrations": migrations}
                    address, port = identity["server_address"], identity["server_port"]
                    endpoint = (address, port) if address is not None and port is not None else None
                    snapshot = _Snapshot(report, endpoint, identity["database_name"],
                                         identity["effective_role"], identity["session_role"], schemas)
            # Exiting both contexts is part of successful inspection.
        return snapshot
    except _ReadOnlyNotConfirmed:
        return {"status": "error", "error_code": "read_only_not_confirmed"}
    except Exception:
        # Deliberately omit exception messages, SQL, and connection parameters.
        return {"status": "error", "error_code": phase}


def inspect_environment(environ: Mapping[str, str], connect: Callable | None = None) -> dict:
    """Inspect each explicit DSN independently; never apply application DB fallback rules.

    No business/user rows are read. Only the migration ledger's version/timestamp
    columns are read after relation kind, visibility and privileges are checked.
    """
    connector = psycopg.connect if connect is None else connect
    cache: dict[str, _Snapshot | dict] = {}
    groups: dict[str, dict[tuple, str]] = {"database": {}, "role": {}, "schema": {}}

    def alias(kind: str, key: tuple) -> str:
        registry = groups[kind]
        if key not in registry:
            registry[key] = f"{kind}{len(registry) + 1}"
        return registry[key]

    targets = []
    for name in _TARGETS:
        dsn = environ.get(name, "").strip()
        if not dsn:
            targets.append({"name": name, "configured": False, "status": "not_configured"})
            continue
        if dsn not in cache:
            cache[dsn] = _inspect(dsn, connector)
        snapshot = cache[dsn]
        if isinstance(snapshot, dict):
            targets.append({"name": name, "configured": True, **snapshot})
            continue
        # A unique token prevents NULL socket endpoints from implying equivalence.
        endpoint = snapshot.endpoint if snapshot.endpoint is not None else (id(snapshot),)
        database_key = (endpoint, snapshot.database)
        target = {"name": name, "configured": True, **deepcopy(snapshot.report)}
        target["database_group"] = alias("database", database_key)
        target["role_group"] = alias("role", (endpoint, snapshot.effective_role))
        target["session_role_group"] = alias("role", (endpoint, snapshot.session_role))
        for table, schema_name in zip(target["tables"], snapshot.schemas, strict=True):
            table["schema_group"] = alias("schema", (database_key, schema_name))
        targets.append(target)
    return {"version": 1, "targets": targets, "identity_limit": _IDENTITY_LIMIT}

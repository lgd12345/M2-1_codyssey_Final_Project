from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest
from psycopg import sql

from app import db_metadata


TABLE_NAMES = (
    "app_user", "app_session", "app_login_failure", "agent_run",
    "agent_run_asset", "rag_document", "rag_embedding_config", "rag_schema_migration",
)
SECRET_DSN = "postgresql://secret_role:secret_password@secret-host.invalid:5432/secret_db"
APPLIED_AT = datetime(2026, 11, 9, 8, 30, tzinfo=timezone.utc)


def relation(name="rag_schema_migration", **changes):
    row = {"name": name, "schema_name": 'secret_role', "kind": "r",
           "visible": True, "schema_usage": True, "select": True,
           "insert": False, "update": False, "delete": False, "rls": False}
    return {**row, **changes}


def scenario(**changes):
    data = {
        "identity": {"database_name": "secret_db", "effective_role": "secret_role",
                     "session_role": "secret_login_role", "server_address": "192.0.2.41",
                     "server_port": 5432, "schema_name": "secret_role",
                     "server_version_num": "160004", "read_only": "on",
                     "connect_privilege": True},
        "schema": {"usage": True, "create": False},
        "tables": [relation()],
        "migrations": [{"version": "003_auth", "applied_at": APPLIED_AT}],
    }
    return {**data, **changes}


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params=None):
        text = query.as_string(None) if isinstance(query, sql.Composable) else query
        text = " ".join(text.split())
        self.connection.events.append(("execute", text, params))
        data = self.connection.data
        if text.startswith("SET "):
            self.rows = []
        elif "AS database_name" in text:
            self.rows = [deepcopy(data["identity"])]
        elif "FROM pg_catalog.pg_namespace WHERE nspname" in text:
            self.rows = [] if data["schema"] is None else [deepcopy(data["schema"])]
        elif "FROM pg_catalog.unnest" in text:
            assert params == (list(TABLE_NAMES),)
            present = {row["name"] for row in data["tables"]}
            self.rows = [{"name": name, "present": name in present} for name in TABLE_NAMES]
        elif "FROM pg_catalog.pg_class AS c JOIN" in text:
            assert params == (list(TABLE_NAMES),)
            self.rows = deepcopy(data["tables"])
        elif text.startswith("SELECT version, applied_at FROM "):
            if data.get("migration_error"):
                raise RuntimeError("secret-host.invalid secret_password secret_db secret_role")
            self.rows = deepcopy(data["migrations"])
        else:
            raise AssertionError(f"Unexpected SQL in fake: {text}")
        return self

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchmany(self, count):
        self.connection.events.append(("fetchmany", count))
        result, self.rows = self.rows[:count], self.rows[count:]
        return result


class FakeTransaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        self.connection.events.append(("transaction_enter",))
        return self

    def __exit__(self, exc_type, *_):
        self.connection.events.append(("transaction_exit", exc_type))
        return False


class FakeConnection:
    def __init__(self, data):
        self.data = data
        self.events = []

    def __enter__(self):
        self.events.append(("connection_enter",))
        return self

    def __exit__(self, *_):
        self.events.append(("connection_exit",))
        if self.data.get("close_error"):
            raise RuntimeError("secret_password")
        return False

    def transaction(self):
        return FakeTransaction(self)

    def cursor(self, **kwargs):
        assert kwargs == {"row_factory": db_metadata.dict_row}
        return FakeCursor(self)


class FakeConnect:
    def __init__(self, data=None, by_dsn=None):
        self.data = scenario() if data is None else data
        self.by_dsn = {} if by_dsn is None else by_dsn
        self.calls = []
        self.connections = []

    def __call__(self, dsn, **kwargs):
        self.calls.append((dsn, kwargs))
        data = self.by_dsn.get(dsn, self.data)
        if isinstance(data, Exception):
            raise data
        connection = FakeConnection(data)
        self.connections.append(connection)
        return connection


@pytest.fixture(autouse=True)
def forbid_real_connections(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("A test attempted a real database connection")

    monkeypatch.setattr(db_metadata.psycopg, "connect", forbidden)


def run(data=None, environ=None):
    connector = FakeConnect(data)
    result = db_metadata.inspect_environment(
        {"DATABASE_URL": SECRET_DSN} if environ is None else environ,
        connect=connector,
    )
    return result, connector


def sql_statements(connector):
    return [event[1] for connection in connector.connections for event in connection.events
            if event[0] == "execute"]


def test_unconfigured_targets_never_connect_or_fall_back_to_test_database():
    result, connector = run(environ={"DATABASE_URL": " \t ", "TEST_DATABASE_URL": SECRET_DSN})
    assert connector.calls == []
    assert result["targets"] == [
        {"name": "DATABASE_URL", "configured": False, "status": "not_configured"},
        {"name": "RAG_DATABASE_URL", "configured": False, "status": "not_configured"},
    ]


def test_explicit_rag_target_does_not_populate_database_target():
    result, connector = run(environ={"RAG_DATABASE_URL": SECRET_DSN})
    assert len(connector.calls) == 1
    assert result["targets"][0]["configured"] is False
    assert result["targets"][1]["status"] == "ok"


def test_default_connector_uses_only_injected_fake_psycopg_connect(monkeypatch):
    connector = FakeConnect()
    monkeypatch.setattr(db_metadata.psycopg, "connect", connector)
    result = db_metadata.inspect_environment({"DATABASE_URL": SECRET_DSN})
    assert result["targets"][0]["status"] == "ok"
    assert connector.calls == [(SECRET_DSN, {"connect_timeout": 3, "autocommit": True})]


def test_transaction_guards_precede_metadata_and_reads_are_bounded():
    result, connector = run()
    statements = sql_statements(connector)
    assert statements[:3] == ["SET TRANSACTION READ ONLY",
                              "SET LOCAL statement_timeout = '2s'",
                              "SET LOCAL lock_timeout = '500ms'"]
    assert all(statement.startswith("SELECT ") for statement in statements[3:])
    events = connector.connections[0].events
    assert events.index(("transaction_enter",)) < events.index(("execute", statements[0], None))
    assert [event[1] for event in events if event[0] == "fetchmany"] == [9, 101, 101]
    assert result["targets"][0]["read_only"] is True
    assert "FROM pg_catalog.pg_class" in " ".join(statements)


@pytest.mark.parametrize("read_only", ["off", None, "true"])
def test_unconfirmed_actual_read_only_aborts_before_further_metadata(read_only):
    data = scenario()
    data["identity"]["read_only"] = read_only
    result, connector = run(data)
    assert result["targets"][0] == {"name": "DATABASE_URL", "configured": True,
                                   "status": "error", "error_code": "read_only_not_confirmed"}
    assert len(sql_statements(connector)) == 4


def test_one_failed_target_does_not_prevent_independent_other_inspection():
    connector = FakeConnect(by_dsn={"bad": RuntimeError(SECRET_DSN)})
    result = db_metadata.inspect_environment(
        {"DATABASE_URL": "bad", "RAG_DATABASE_URL": "good"}, connect=connector)
    assert result["targets"][0]["error_code"] == "connection_failed"
    assert result["targets"][1]["status"] == "ok"
    assert [call[0] for call in connector.calls] == ["bad", "good"]


def test_identical_dsn_is_inspected_once_and_result_objects_are_independent():
    result, connector = run(environ={"DATABASE_URL": SECRET_DSN, "RAG_DATABASE_URL": SECRET_DSN})
    first, second = result["targets"]
    assert len(connector.calls) == 1
    assert first["database_group"] == second["database_group"]
    assert first["role_group"] == second["role_group"]
    first["tables"][0]["select"] = False
    assert second["tables"][0]["select"] is True


def test_privileges_presence_rls_and_timestamp_are_reported_individually():
    data = scenario(tables=[relation(), relation("app_user", insert=True, delete=True, rls=True)])
    result, _ = run(data)
    target = result["targets"][0]
    assert target["server_version_num"] == 160004
    assert target["connect_privilege"] is True
    assert target["current_schema"] == {"present": True, "usage": True, "create": False}
    assert target["table_presence"] == {name: name in ("rag_schema_migration", "app_user")
                                        for name in TABLE_NAMES}
    user = target["tables"][1]
    assert {name: user[name] for name in ("select", "insert", "update", "delete", "rls")} == {
        "select": True, "insert": True, "update": False, "delete": True, "rls": True}
    assert target["migrations"]["rows"] == [{"version": "003_auth", "applied_at": APPLIED_AT.isoformat()}]
    json.dumps(result)


def test_missing_current_schema_is_not_queried_by_name():
    data = scenario()
    data["identity"]["schema_name"] = None
    result, connector = run(data)
    assert result["targets"][0]["current_schema"] == {"present": False, "usage": False, "create": False}
    assert not any("WHERE nspname" in query for query in sql_statements(connector))


@pytest.mark.parametrize("tables,status", [
    ([], "not_found"),
    ([relation(visible=False)], "not_visible"),
    ([relation(schema_usage=False)], "table_select_not_confirmed"),
    ([relation(select=False)], "table_select_not_confirmed"),
    ([relation(kind="v")], "unsupported_relation_kind"),
    ([relation(kind="m")], "unsupported_relation_kind"),
    ([relation(kind="f")], "unsupported_relation_kind"),
    ([relation(), relation(schema_name="other")], "ambiguous"),
])
def test_migration_rows_require_exact_supported_visible_readable_relation(tables, status):
    result, connector = run(scenario(tables=tables))
    assert result["targets"][0]["migrations"]["status"] == status
    assert not any(query.startswith("SELECT version, applied_at FROM") for query in sql_statements(connector))


def test_migration_identifier_quotes_exact_schema_and_accepts_partitioned_table():
    result, connector = run(scenario(tables=[relation(schema_name='private"schema', kind="p", rls=True)]))
    query = sql_statements(connector)[-1]
    assert query == 'SELECT version, applied_at FROM "private""schema"."rag_schema_migration" ORDER BY version LIMIT 101'
    assert result["targets"][0]["migrations"]["row_security_active"] is True


def test_table_truncation_does_not_invent_absence_or_read_incomplete_migration_selection():
    tables = [relation()] + [relation("agent_run", schema_name=f"schema{i}") for i in range(100)]
    result, connector = run(scenario(tables=tables))
    target = result["targets"][0]
    assert target["tables_truncated"] is True
    assert len(target["tables"]) == 100
    assert target["table_presence"]["rag_schema_migration"] is True
    assert target["table_presence"]["app_user"] is False
    assert target["migrations"]["status"] == "not_inspected_truncated"
    assert not sql_statements(connector)[-1].startswith("SELECT version, applied_at FROM")


def test_migration_rows_are_limited_and_marked_truncated():
    rows = [{"version": f"{i:03d}_migration", "applied_at": APPLIED_AT} for i in range(101)]
    result, _ = run(scenario(migrations=rows))
    migrations = result["targets"][0]["migrations"]
    assert migrations["status"] == "ok"
    assert len(migrations["rows"]) == 100
    assert migrations["truncated"] is True


def test_observed_identity_groups_distinguish_database_and_effective_role():
    first, second = scenario(), scenario()
    second["identity"].update(database_name="another_secret_db", effective_role="another_secret_role")
    connector = FakeConnect(by_dsn={"first": first, "second": second})
    result = db_metadata.inspect_environment({"DATABASE_URL": "first", "RAG_DATABASE_URL": "second"}, connect=connector)
    left, right = result["targets"]
    assert left["database_group"] != right["database_group"]
    assert left["role_group"] != right["role_group"]
    assert left["session_role_group"] == right["session_role_group"]
    assert "do not prove cluster identity" in result["identity_limit"]


def test_unknown_endpoint_is_not_equated_across_different_dsns():
    data = scenario()
    data["identity"].update(server_address=None, server_port=None)
    result, _ = run(data, {"DATABASE_URL": "one", "RAG_DATABASE_URL": "two"})
    left, right = result["targets"]
    assert left["database_group"] != right["database_group"]
    assert left["role_group"] != right["role_group"]


@pytest.mark.parametrize("data,code", [
    (scenario(migration_error=True), "migration_read_failed"),
    (scenario(migrations=[{"version": "untrusted secret_password", "applied_at": APPLIED_AT}]), "migration_read_failed"),
    (scenario(close_error=True), "metadata_failed"),
])
def test_failed_inspection_returns_only_fixed_error_code(data, code):
    result, _ = run(data)
    assert result["targets"][0] == {"name": "DATABASE_URL", "configured": True,
                                   "status": "error", "error_code": code}
    serialized = json.dumps(result)
    for secret in (SECRET_DSN, "secret_password", "secret_db", "secret_role", "secret-host.invalid", "192.0.2.41"):
        assert secret not in serialized


def test_successful_report_omits_connection_identity_schema_and_user_rows():
    result, connector = run()
    serialized = json.dumps(result)
    for secret in (SECRET_DSN, "secret_password", "secret_db", "secret_role", "secret_login_role",
                   "secret-host.invalid", "192.0.2.41"):
        assert secret not in serialized
    for query in sql_statements(connector):
        if query.startswith("SELECT ") and "pg_catalog." not in query:
            assert query.startswith('SELECT version, applied_at FROM "secret_role"."rag_schema_migration" ')
        assert "SELECT *" not in query

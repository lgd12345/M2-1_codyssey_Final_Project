"""Single analysis run persistence without chat state or a real database."""
from contextlib import nullcontext
from uuid import uuid4

import psycopg
import pytest

from app.runs import service


def test_create_analysis_run_does_not_require_conversation_state():
    user_id, run_id = uuid4(), uuid4()
    statements = []

    class Connection:
        def transaction(self):
            return nullcontext()

        def execute(self, statement, arguments):
            statements.append((statement, arguments))
            return self

        def fetchone(self):
            return (run_id,)

    assert service.create_run(Connection(), user_id, "sample question") == run_id
    assert len(statements) == 2
    assert "interrupted" in statements[0][0]  # Orphan recovery is still preserved.
    query, arguments = statements[1]
    assert query == (
        "INSERT INTO agent_run(user_id, question, worker_id) VALUES (%s,%s,%s) RETURNING id"
    )
    assert arguments == (user_id, "sample question", service.PROCESS_ID)


def test_single_active_analysis_run_constraint_is_still_translated():
    class Connection:
        def transaction(self):
            return nullcontext()

        def execute(self, statement, _arguments):
            if statement.startswith("INSERT"):
                raise psycopg.errors.UniqueViolation("synthetic duplicate")

    with pytest.raises(service.RunInProgress):
        service.create_run(Connection(), uuid4(), "sample question")

"""Agent run persistence. Every read is scoped to the owning user."""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from app.agent_rag.agent import AgentOutputValidationError, ManualAgentResult
from app.agent_rag.settings import AgentNotConfigured
from app.auth.service import AuthError

# One id per server process: a running row owned by any other process was orphaned by a restart.
PROCESS_ID = uuid4().hex
LIST_LIMIT = 50


class RunInProgress(AuthError):
    status_code, code = 429, "RUN_IN_PROGRESS"
    message = "이미 실행 중인 질문이 있습니다. 완료된 뒤 다시 시도하세요."


class RunNotFound(AuthError):
    status_code, code = 404, "RUN_NOT_FOUND"
    message = "실행 기록을 찾을 수 없습니다."


def _json(value: Any) -> Jsonb:
    return Jsonb(value, dumps=lambda item: json.dumps(item, ensure_ascii=False, default=str))


def error_code_for(error: BaseException) -> str:
    """Map an exception to a stable public code. The exception text is never stored."""
    from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior

    if isinstance(error, AgentNotConfigured):
        return "agent_not_configured"
    if isinstance(error, (AgentOutputValidationError, UnexpectedModelBehavior)):
        return "invalid_agent_output"
    if isinstance(error, ModelHTTPError):
        return "llm_unavailable"
    try:
        import openai
        if isinstance(error, openai.APIError):
            return "llm_unavailable"
    except ImportError:  # pragma: no cover - openai ships with pydantic-ai[openai]
        pass
    if isinstance(error, psycopg.Error):
        return "database_unavailable"
    return "agent_error"


def recover_orphans(connection) -> None:
    connection.execute(
        """UPDATE agent_run SET status='failed', error_code='interrupted', finished_at=now()
           WHERE status IN ('queued','running') AND worker_id IS DISTINCT FROM %s""", (PROCESS_ID,))


def create_run(connection, user_id: UUID, question: str, conversation_id: str | None = None) -> UUID:
    recover_orphans(connection)
    try:
        with connection.transaction():
            return connection.execute(
                "INSERT INTO agent_run(user_id, question, worker_id, conversation_id) VALUES (%s,%s,%s,%s) RETURNING id",
                (user_id, question, PROCESS_ID, conversation_id)).fetchone()[0]
    except psycopg.errors.UniqueViolation:
        raise RunInProgress() from None


def verified_citations(connection, user_id: UUID, conversation_id: str | None, limit: int = 20) -> list[dict[str, Any]]:
    """Sources the server validated in this user's earlier *succeeded* turns of the same chat."""
    if not conversation_id:
        return []
    rows = connection.execute(
        """SELECT citations FROM agent_run WHERE user_id=%s AND conversation_id=%s AND status='succeeded'
           ORDER BY created_at DESC LIMIT %s""", (user_id, conversation_id, limit)).fetchall()
    seen: dict[tuple[str, int], dict[str, Any]] = {}
    for (citations,) in rows:
        for item in citations or []:
            key = (item.get("document_sha256"), item.get("page"))
            if all(key) and key not in seen:
                seen[key] = {"document_sha256": key[0], "page": key[1],
                             "printed_page": item.get("printed_page"), "title": str(item.get("title", ""))}
    return list(seen.values())


def mark_running(connection, run_id: UUID) -> None:
    connection.execute("UPDATE agent_run SET status='running', started_at=now() WHERE id=%s AND status='queued'",
                       (run_id,))


def store_success(connection, run_id: UUID, result: ManualAgentResult) -> None:
    data = result.to_dict()
    with connection.transaction():
        connection.execute(
            """UPDATE agent_run SET status='succeeded', answer_status=%s, answer_markdown=%s, citations=%s,
                      tool_calls=%s, retrieval_status=%s, finished_at=now() WHERE id=%s""",
            (data["status"], data["answer_markdown"], _json(data["citations"]), _json(data["tool_calls"]),
             _json(data["retrieval_status"]), run_id))
        for asset in result.assets:
            connection.execute(
                """INSERT INTO agent_run_asset(run_id, asset_id, document_sha256, pdf_page, media_type, data)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (run_id, asset.asset_id, asset.document_sha256, asset.pdf_page, asset.media_type, asset.data))


def store_failure(connection, run_id: UUID, code: str) -> None:
    connection.execute(
        "UPDATE agent_run SET status='failed', error_code=%s, finished_at=now() "
        "WHERE id=%s AND status IN ('queued','running')", (code, run_id))


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def get_run(connection, user_id: UUID, run_id: UUID) -> dict[str, Any]:
    recover_orphans(connection)
    row = connection.execute(
        """SELECT id, question, status, answer_status, answer_markdown, citations, tool_calls,
                  retrieval_status, error_code, created_at, finished_at
           FROM agent_run WHERE id=%s AND user_id=%s""", (run_id, user_id)).fetchone()
    if row is None:
        raise RunNotFound()
    assets = connection.execute(
        "SELECT asset_id, document_sha256, pdf_page, media_type FROM agent_run_asset WHERE run_id=%s ORDER BY asset_id",
        (run_id,)).fetchall()
    return {
        "id": str(row[0]), "question": row[1], "status": row[2], "answer_status": row[3],
        "answer_markdown": row[4], "citations": row[5], "tool_calls": row[6], "retrieval_status": row[7],
        "error_code": row[8], "created_at": _iso(row[9]), "finished_at": _iso(row[10]),
        "assets": [{"asset_id": a[0], "document_sha256": a[1], "pdf_page": a[2], "media_type": a[3],
                    "url": f"/api/v1/agent/runs/{row[0]}/assets/{a[0]}"} for a in assets],
    }


def list_runs(connection, user_id: UUID) -> list[dict[str, Any]]:
    recover_orphans(connection)
    rows = connection.execute(
        """SELECT id, question, status, answer_status, error_code, created_at FROM agent_run
           WHERE user_id=%s ORDER BY created_at DESC LIMIT %s""", (user_id, LIST_LIMIT)).fetchall()
    return [{"id": str(r[0]), "question": r[1], "status": r[2], "answer_status": r[3],
             "error_code": r[4], "created_at": _iso(r[5])} for r in rows]


def get_asset(connection, user_id: UUID, run_id: UUID, asset_id: str) -> tuple[bytes, str]:
    row = connection.execute(
        """SELECT a.data, a.media_type FROM agent_run_asset a JOIN agent_run r ON r.id = a.run_id
           WHERE a.run_id=%s AND a.asset_id=%s AND r.user_id=%s""", (run_id, asset_id, user_id)).fetchone()
    if row is None:
        raise RunNotFound()
    return bytes(row[0]), row[1]

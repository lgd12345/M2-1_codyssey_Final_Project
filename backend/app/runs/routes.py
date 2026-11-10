from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from pydantic import BaseModel, Field, field_validator

from app.agent_rag.agent import ManualAgentResult
from app.agent_rag.runner import AgentSession, open_agent_session, run_manual_agent
from app.auth.deps import database, require_operator_csrf, require_operator
from app.auth.service import SessionInfo
from app.runs import service
from app.runs.stream import start_stream

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/agent", tags=["agent"])
AgentRunner = Callable[[str], Awaitable[ManualAgentResult]]


def get_agent_runner() -> AgentRunner:
    """Dependency seam: tests replace this so no real model is called."""
    return run_manual_agent


def get_agent_session_factory() -> Callable[[], AgentSession]:
    """Dependency seam for the streaming endpoint; tests replace it so no real model is called."""
    return open_agent_session


class RunRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)

    @field_validator("question")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be blank")
        return value


def _parse(run_id: str) -> UUID:
    try:
        return UUID(run_id)
    except ValueError:
        raise service.RunNotFound() from None


def _write(action, *args) -> None:
    with database() as connection:
        action(connection, *args)


async def execute_run(run_id: UUID, question: str, runner: AgentRunner) -> None:
    await asyncio.to_thread(_write, service.mark_running, run_id)
    try:
        result = await runner(question)
    except asyncio.CancelledError:
        await asyncio.shield(asyncio.to_thread(_write, service.store_failure, run_id, "interrupted"))
        raise
    except Exception as error:
        logger.warning("agent run failed: %s", type(error).__name__)  # never the message: it may hold secrets
        await asyncio.to_thread(_write, service.store_failure, run_id, service.error_code_for(error))
        return
    try:
        await asyncio.to_thread(_write, service.store_success, run_id, result)
    except Exception as error:
        logger.warning("agent run result could not be stored: %s", type(error).__name__)
        await asyncio.to_thread(_write, service.store_failure, run_id, "storage_error")


@router.post("/runs", status_code=202)
def create_run(body: RunRequest, background: BackgroundTasks,
               session: SessionInfo = Depends(require_operator_csrf),
               runner: AgentRunner = Depends(get_agent_runner)):
    with database() as connection:
        run_id = service.create_run(connection, session.user.id, body.question)
    background.add_task(execute_run, run_id, body.question, runner)
    return {"id": str(run_id), "status": "queued"}


@router.post("/stream")
async def stream_run(request: Request, session: SessionInfo = Depends(require_operator_csrf),
                     factory: Callable[[], AgentSession] = Depends(get_agent_session_factory)):
    return await start_stream(request, session.user.id, factory)


@router.get("/runs")
def list_runs(session: SessionInfo = Depends(require_operator)):
    with database() as connection:
        return {"runs": service.list_runs(connection, session.user.id)}


@router.get("/runs/{run_id}")
def get_run(run_id: str, session: SessionInfo = Depends(require_operator)):
    with database() as connection:
        return service.get_run(connection, session.user.id, _parse(run_id))


@router.get("/runs/{run_id}/assets/{asset_id}")
def get_asset(run_id: str, asset_id: str, session: SessionInfo = Depends(require_operator)):
    with database() as connection:
        data, media_type = service.get_asset(connection, session.user.id, _parse(run_id), asset_id)
    return Response(content=data, media_type=media_type, headers={
        "Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})

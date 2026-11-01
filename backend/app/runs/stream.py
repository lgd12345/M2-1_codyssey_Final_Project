"""Chat (AI SDK) streaming endpoint logic.

The stream only *shows* the agent working. The run's validated answer, citations and images come from the
same validate/store path as plain runs, so a streamed `final_result` is never the source of truth.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import AsyncIterator, Callable
from uuid import UUID

from fastapi import Request
from pydantic import ValidationError
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from pydantic_ai.ui.vercel_ai._event_stream import VercelAIEventStream
from pydantic_ai.ui.vercel_ai.response_types import ErrorChunk
from pydantic_ai.usage import UsageLimits

from app.agent_rag.agent import AgentOutputValidationError, validate_agent_output
from app.agent_rag.runner import AgentSession
from app.agent_rag.settings import AgentNotConfigured
from app.auth.deps import database
from app.auth.service import AuthError
from app.runs import service

logger = logging.getLogger(__name__)
MAX_QUESTION = 4000
_CHAT_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class BadChatRequest(AuthError):
    status_code, code = 422, "INVALID_QUESTION"
    message = "질문을 확인할 수 없습니다. 비어 있거나 너무 길지 않은지 확인하세요."


class AgentUnavailable(AuthError):
    status_code, code = 503, "AGENT_UNAVAILABLE"
    message = "에이전트를 시작할 수 없습니다."


class AgentNotConfiguredError(AgentUnavailable):
    code = "AGENT_NOT_CONFIGURED"
    message = "에이전트 설정(LLM)이 비어 있습니다."


def _write(action, *args) -> None:
    with database() as connection:
        action(connection, *args)


class SafeEventStream(VercelAIEventStream):
    """The stock stream sends str(error) to the browser; send only a fixed code instead."""
    # Shared with the adapter: the stream object may be rebuilt, so the code must not live on one instance.
    error_box: dict = {}

    async def on_error(self, error: Exception):
        code = service.error_code_for(error)
        self.error_box["code"] = code
        logger.warning("agent stream failed: %s", type(error).__name__)  # never the message
        async for chunk in super().on_error(error):
            yield ErrorChunk(error_text=code) if isinstance(chunk, ErrorChunk) else chunk


class SafeAdapter(VercelAIAdapter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.error_box: dict = {}

    def build_event_stream(self):
        stream = SafeEventStream(self.run_input, accept=self.accept, sdk_version=self.sdk_version,
                                 server_message_id=self.server_message_id)
        stream.error_box = self.error_box
        return stream


async def extract_question(request: Request) -> str:
    """The question is the last user message's text; earlier turns are the client's own context."""
    try:
        body = await request.json()
    except ValueError:
        raise BadChatRequest() from None
    messages = body.get("messages") if isinstance(body, dict) else None
    last = messages[-1] if isinstance(messages, list) and messages else None
    if not isinstance(last, dict) or last.get("role") != "user":
        raise BadChatRequest()
    parts = last.get("parts") if isinstance(last.get("parts"), list) else []
    text = "".join(p["text"] for p in parts
                   if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str)).strip()
    if not text or len(text) > MAX_QUESTION:
        raise BadChatRequest()
    return text


async def chat_id_of(request: Request) -> str | None:
    """The client's chat id, only if well-formed. It selects the caller's own earlier runs, nothing more."""
    try:
        body = await request.json()
    except ValueError:
        return None
    value = body.get("id") if isinstance(body, dict) else None
    return value if isinstance(value, str) and _CHAT_ID.fullmatch(value) else None


async def guard_stream(stream: AsyncIterator, run_id: UUID, *,
                       error_code: Callable[[], str | None] = lambda: None,
                       cleanup: Callable[[], object] | None = None) -> AsyncIterator:
    """Relay events; however the stream ends (done, error, browser closed), the run is never left active."""
    try:
        async for chunk in stream:
            yield chunk
    finally:
        try:
            # No-op when the run already finished: only queued/running rows are changed.
            await asyncio.shield(asyncio.to_thread(_write, service.store_failure, run_id,
                                                   error_code() or "interrupted"))
        finally:
            if cleanup is not None:
                await asyncio.shield(cleanup())


async def start_stream(request: Request, user_id: UUID, factory: Callable[[], AgentSession]):
    question = await extract_question(request)
    chat_id = await chat_id_of(request)

    def begin() -> tuple[UUID, list]:
        with database() as connection:
            earlier = service.verified_citations(connection, user_id, chat_id)
            run_id = service.create_run(connection, user_id, question, chat_id)
            service.mark_running(connection, run_id)
            return run_id, earlier

    run_id, earlier = await asyncio.to_thread(begin)  # ownership + one-active-run rule, before anything streams

    async def fail(code: str) -> None:
        await asyncio.to_thread(_write, service.store_failure, run_id, code)

    try:
        agent_session = factory()
    except Exception as error:
        await fail(service.error_code_for(error))
        raise (AgentNotConfiguredError() if isinstance(error, AgentNotConfigured) else AgentUnavailable()) from None
    for item in earlier:  # evidence this server already validated for this user in this chat
        agent_session.tools.available_citations[(item["document_sha256"], item["page"])] = item
    try:
        adapter = await SafeAdapter.from_request(request, agent=agent_session.agent, sdk_version=7)
    except ValidationError:
        await fail("invalid_request")
        await agent_session.close()
        raise BadChatRequest() from None

    async def on_complete(result) -> None:
        try:
            validated = validate_agent_output(result.output, agent_session.tools)
        except Exception as error:
            if isinstance(error, AgentOutputValidationError):
                # Our own fixed wording (never the model's text), so the cause of a rejection is visible in dev.
                logger.warning("agent output rejected: %s", error)
            await fail(service.error_code_for(error))
            return
        try:
            await asyncio.to_thread(_write, service.store_success, run_id, validated)
        except Exception as error:
            logger.warning("agent run result could not be stored: %s", type(error).__name__)
            await fail("storage_error")

    events = adapter.run_stream(usage_limits=UsageLimits(request_limit=None), on_complete=on_complete)
    response = adapter.streaming_response(guard_stream(
        events, run_id,
        error_code=lambda: adapter.error_box.get("code"),
        cleanup=agent_session.close))
    response.headers["X-Run-Id"] = str(run_id)
    return response

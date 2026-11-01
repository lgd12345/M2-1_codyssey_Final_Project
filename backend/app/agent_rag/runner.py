"""Production entry points used by the API and CLI: settings, optional embedder, then the agent."""
from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Awaitable, Callable

from pydantic_ai import Agent

from app.agent_rag.agent import ManualAgentResult, build_agent, make_llm, run_agent
from app.agent_rag.embedding import GeminiEmbedder
from app.agent_rag.embedding_events import record_embedding_error
from app.agent_rag.settings import AgentSettings
from app.agent_rag.tools import ManualAgentTools


def _embedder(settings: AgentSettings) -> GeminiEmbedder | None:
    if os.getenv("GEMINI_EMBEDDING_BASE_URL", "").strip() and os.getenv("GEMINI_EMBEDDING_MODEL", "").strip():
        return GeminiEmbedder.from_env(
            error_sink=lambda event: record_embedding_error(event, database_url=settings.database_url)
        )
    return None


async def run_manual_agent(question: str) -> ManualAgentResult:
    settings = AgentSettings.from_env()
    return await run_agent(question, settings=settings, embedder=_embedder(settings))


@dataclass
class AgentSession:
    """One agent run's objects. `tools` carries per-run state, so a session is never shared."""
    agent: Agent
    tools: ManualAgentTools
    close: Callable[[], Awaitable[None]]


def open_agent_session() -> AgentSession:
    settings = AgentSettings.from_env()
    settings.validate_llm()  # AgentNotConfigured before any run is started
    model, client = make_llm(settings)
    agent, tools = build_agent(settings, embedder=_embedder(settings), model=model)
    return AgentSession(agent, tools, close=client.close)

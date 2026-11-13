"""Production entry points used by the API and CLI: settings, optional embedder, then the agent."""
from __future__ import annotations

import os

from app.agent_rag.agent import ManualAgentResult, run_agent
from app.agent_rag.embedding import GeminiEmbedder, configured_embedder
from app.agent_rag.embedding_events import record_embedding_error
from app.agent_rag.settings import AgentSettings


def _embedder(settings: AgentSettings) -> GeminiEmbedder | None:
    provider = os.getenv("RAG_EMBEDDING_PROVIDER", "gemini").strip().lower()
    prefix = "QWEN" if provider == "qwen" else "GEMINI"
    if os.getenv(f"{prefix}_EMBEDDING_BASE_URL", "").strip() and os.getenv(f"{prefix}_EMBEDDING_MODEL", "qwen3-embedding-0.6b" if prefix == "QWEN" else "").strip():
        return configured_embedder(provider=provider,
            error_sink=lambda event: record_embedding_error(event, database_url=settings.database_url)
        )
    return None


async def run_manual_agent(question: str) -> ManualAgentResult:
    settings = AgentSettings.from_env()
    return await run_agent(question, settings=settings, embedder=_embedder(settings))

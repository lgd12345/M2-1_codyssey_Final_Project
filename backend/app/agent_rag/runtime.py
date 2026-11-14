"""Runtime embedder for retrieval: the configured provider when its endpoint is set, otherwise none (keyword search only)."""
from __future__ import annotations

import os

from app.agent_rag.embedding import DEFAULT_EMBEDDING_PROVIDER, GeminiEmbedder, configured_embedder
from app.agent_rag.embedding_events import record_embedding_error
from app.agent_rag.settings import AgentSettings


def runtime_embedder(settings: AgentSettings) -> GeminiEmbedder | None:
    provider = os.getenv("RAG_EMBEDDING_PROVIDER", DEFAULT_EMBEDDING_PROVIDER).strip().lower()
    prefix = "QWEN" if provider == "qwen" else "GEMINI"
    default_model = "qwen3-embedding-0.6b" if prefix == "QWEN" else ""
    if os.getenv(f"{prefix}_EMBEDDING_BASE_URL", "").strip() and os.getenv(f"{prefix}_EMBEDDING_MODEL", default_model).strip():
        return configured_embedder(provider=provider,
                                   error_sink=lambda event: record_embedding_error(event, database_url=settings.database_url))
    return None

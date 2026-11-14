"""The chat model used for service-request analysis: an OpenAI-compatible proxy configured in backend/.env."""
from __future__ import annotations

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.agent_rag.settings import AgentSettings


def make_llm(settings: AgentSettings):
    """Chat model over the configured proxy; the caller closes the returned client."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key or "no-key",
                         timeout=settings.llm_timeout_seconds, max_retries=0)
    return OpenAIChatModel(settings.llm_model, provider=OpenAIProvider(openai_client=client)), client

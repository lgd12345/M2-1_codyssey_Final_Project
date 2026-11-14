"""Qwen is the default embedding provider, so the minimal configuration is just its base URL."""
from pathlib import Path

import pytest

from app.agent_rag.embedding import DEFAULT_EMBEDDING_PROVIDER, GeminiEmbedder, QwenEmbedder, configured_embedder
from app.agent_rag.runtime import runtime_embedder
from app.agent_rag.settings import AgentSettings

SETTINGS = AgentSettings('', '', '', 60, 'postgresql://x/db', Path('cache'), 150)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ('RAG_EMBEDDING_PROVIDER', 'QWEN_EMBEDDING_BASE_URL', 'QWEN_EMBEDDING_API_KEY', 'QWEN_EMBEDDING_MODEL',
                 'QWEN_EMBEDDING_DIMENSION', 'QWEN_EMBEDDING_TIMEOUT_SECONDS', 'QWEN_EMBEDDING_MAX_RETRIES',
                 'GEMINI_EMBEDDING_BASE_URL', 'GEMINI_EMBEDDING_MODEL', 'GEMINI_EMBEDDING_API_KEY'):
        monkeypatch.delenv(name, raising=False)


def test_the_default_provider_is_qwen():
    assert DEFAULT_EMBEDDING_PROVIDER == 'qwen'


def test_only_the_qwen_base_url_is_needed_and_everything_else_has_a_default(monkeypatch):
    monkeypatch.setenv('QWEN_EMBEDDING_BASE_URL', 'http://embeddings.internal/v1')
    embedder = configured_embedder()
    assert isinstance(embedder, QwenEmbedder) and embedder.PROVIDER == 'qwen'
    assert embedder.model == 'qwen3-embedding-0.6b' and embedder.dimension == 1024
    assert isinstance(runtime_embedder(SETTINGS), QwenEmbedder)


def test_without_any_embedding_endpoint_retrieval_is_keyword_only():
    assert runtime_embedder(SETTINGS) is None


def test_gemini_remains_an_explicit_opt_in(monkeypatch):
    monkeypatch.setenv('GEMINI_EMBEDDING_BASE_URL', 'http://gemini.internal/v1')
    monkeypatch.setenv('GEMINI_EMBEDDING_MODEL', 'gemini-embedding-2')
    assert runtime_embedder(SETTINGS) is None  # a configured Gemini endpoint alone does not switch the provider
    monkeypatch.setenv('RAG_EMBEDDING_PROVIDER', 'gemini')
    assert isinstance(runtime_embedder(SETTINGS), GeminiEmbedder)
    assert isinstance(configured_embedder(), GeminiEmbedder)


def test_an_unknown_provider_is_refused(monkeypatch):
    monkeypatch.setenv('RAG_EMBEDDING_PROVIDER', 'openai')
    with pytest.raises(ValueError, match='gemini or qwen'):
        configured_embedder()

import json
from urllib.error import HTTPError

import pytest

from app.agent_rag.embedding import EmbeddingUnavailable, GeminiEmbedder


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, *_args):
        return json.dumps(self.payload).encode()


def test_embedding_response_is_validated_and_vectors_are_normalized(monkeypatch):
    response = {"data": [{"index": 0, "embedding": [3.0, 4.0]}]}
    monkeypatch.setattr("app.agent_rag.embedding.urlopen", lambda *_a, **_kw: FakeResponse(response))
    embedder = GeminiEmbedder("https://example.test/v1", "secret", "test", dimension=2, retries=0)
    assert embedder.embed_query("hello") == [0.6, 0.8]


def test_retryable_429_retries_and_succeeds_without_logging_secrets(monkeypatch):
    calls = []
    waits = []

    def fake_open(request, timeout):
        calls.append(request)
        if len(calls) == 1:
            raise HTTPError(request.full_url, 429, "quota", {"Retry-After": "0"}, None)
        return FakeResponse({"data": [{"index": 0, "embedding": [0.0, 2.0]}]})

    monkeypatch.setattr("app.agent_rag.embedding.urlopen", fake_open)
    monkeypatch.setattr("app.agent_rag.embedding.sleep", waits.append)
    monkeypatch.setattr("app.agent_rag.embedding.random_uniform", lambda *_a: 0.0)
    embedder = GeminiEmbedder("https://example.test/v1", "secret", "test", dimension=2, retries=2)
    assert embedder.embed_query("question") == [0.0, 1.0]
    assert len(calls) == 2
    assert waits == [0.0]


def test_retry_after_is_honored_even_when_longer_than_exponential_backoff(monkeypatch):
    calls = []
    waits = []

    def fake_open(request, timeout):
        calls.append(request)
        if len(calls) == 1:
            raise HTTPError(request.full_url, 429, "quota", {"Retry-After": "45"}, None)
        return FakeResponse({"data": [{"index": 0, "embedding": [1.0, 0.0]}]})

    monkeypatch.setattr("app.agent_rag.embedding.urlopen", fake_open)
    monkeypatch.setattr("app.agent_rag.embedding.sleep", waits.append)
    embedder = GeminiEmbedder("https://example.test/v1", "secret", "test", dimension=2,
                              retries=1, max_backoff_seconds=2)
    assert embedder.embed_query("question") == [1.0, 0.0]
    assert waits == [45.0]


def test_auth_error_is_not_retried(monkeypatch):
    calls = []

    def fake_open(request, timeout):
        calls.append(request)
        raise HTTPError(request.full_url, 401, "unauthorized", {}, None)

    monkeypatch.setattr("app.agent_rag.embedding.urlopen", fake_open)
    embedder = GeminiEmbedder("https://example.test/v1", "secret", "test", dimension=2, retries=3)
    with pytest.raises(EmbeddingUnavailable, match="authentication"):
        embedder.embed_query("question")
    assert len(calls) == 1


def test_batch_limit_is_100(monkeypatch):
    embedder = GeminiEmbedder("https://example.test/v1", "secret", "test", dimension=2)
    with pytest.raises(ValueError, match="100"):
        embedder.embed_documents(["x"] * 101)

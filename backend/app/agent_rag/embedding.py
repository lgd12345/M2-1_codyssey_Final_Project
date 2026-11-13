from __future__ import annotations

import json
import logging
import math
import os
import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def _safe_urlopen(request, *, timeout):
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    return opener.open(request, timeout=timeout)


urlopen = _safe_urlopen
sleep = time.sleep
random_uniform = random.uniform
log = logging.getLogger(__name__)


class EmbeddingUnavailable(RuntimeError):
    def __init__(self, category: str, *, retry_attempts: int = 0, http_status: int | None = None):
        self.category = category
        self.retry_attempts = retry_attempts
        self.http_status = http_status
        super().__init__(category)


class GeminiEmbedder:
    """OpenAI-compatible Gemini embeddings client with bounded transient-error retries."""

    MAX_BATCH_SIZE = 100
    DEFAULT_DIMENSION = 3072
    PROVIDER = "gemini"
    INPUT_FORMAT = "raw-v1"

    def __init__(self, base_url: str, api_key: str, model: str, *, dimension: int = DEFAULT_DIMENSION,
                 timeout: float = 30.0, retries: int = 5, backoff_seconds: float = 1.0,
                 max_backoff_seconds: float = 30.0, error_sink: Callable[[dict], None] | None = None):
        if not model.strip():
            raise ValueError("embedding model is required")
        if not 1 <= dimension <= 3072:
            raise ValueError("embedding dimension must be between 1 and 3072")
        if not 0 <= retries <= 10:
            raise ValueError("embedding retries must be between 0 and 10")
        parsed = urlsplit(base_url.strip())
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("invalid embedding base URL")
        path = parsed.path.rstrip("/")
        if path.endswith("/embeddings"):
            endpoint_path = path
        elif path.endswith(("/v1", "/openai", "/v1beta/openai")):
            endpoint_path = f"{path}/embeddings"
        else:
            endpoint_path = f"{path}/v1/embeddings"
        self.endpoint = urlunsplit((parsed.scheme, parsed.netloc, endpoint_path, "", ""))
        self._api_key = api_key.strip()
        self.model = model.strip()
        self.dimension = dimension
        self.timeout = timeout
        self.retries = retries
        self.backoff_seconds = max(0.0, backoff_seconds)
        self.max_backoff_seconds = max(self.backoff_seconds, max_backoff_seconds)
        self.error_sink = error_sink
        self.last_retry_attempts = 0

    def __repr__(self) -> str:
        return f"GeminiEmbedder(model={self.model!r}, dimension={self.dimension}, key=***)"

    @property
    def identity(self) -> dict[str, str | int]:
        return {"provider": self.PROVIDER, "model": self.model, "dimension": self.dimension,
                "endpoint": self.endpoint, "input_format": self.INPUT_FORMAT}

    @property
    def config_id(self) -> str:
        import hashlib
        return hashlib.sha256(json.dumps(self.identity, sort_keys=True).encode()).hexdigest()

    @classmethod
    def from_env(cls, *, error_sink: Callable[[dict], None] | None = None) -> "GeminiEmbedder":
        base = os.getenv("GEMINI_EMBEDDING_BASE_URL", "").strip()
        key = os.getenv("GEMINI_EMBEDDING_API_KEY", "").strip()
        model = os.getenv("GEMINI_EMBEDDING_MODEL", "").strip()
        if not base or not model:
            raise ValueError("GEMINI_EMBEDDING_BASE_URL and GEMINI_EMBEDDING_MODEL must be configured")
        return cls(base, key, model,
                   timeout=float(os.getenv("GEMINI_EMBEDDING_TIMEOUT_SECONDS", "30")),
                   retries=int(os.getenv("GEMINI_EMBEDDING_MAX_RETRIES", "5")),
                   backoff_seconds=float(os.getenv("GEMINI_EMBEDDING_BACKOFF_SECONDS", "1")),
                   max_backoff_seconds=float(os.getenv("GEMINI_EMBEDDING_MAX_BACKOFF_SECONDS", "30")),
                   error_sink=error_sink)

    def _retry_after(self, error: HTTPError) -> float | None:
        raw = error.headers.get("Retry-After") if error.headers else None
        if not raw:
            return None
        try:
            value = float(raw)
            return max(0.0, value) if math.isfinite(value) else None
        except (TypeError, ValueError):
            try:
                date = parsedate_to_datetime(raw)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                return max(0.0, (date - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                return None

    def _record_error(self, category: str, status: int | None, retry_after: float | None,
                      count: int, operation: str) -> None:
        if self.error_sink is None:
            return
        try:
            self.error_sink({"provider": self.PROVIDER, "model": self.model, "operation": operation,
                             "http_status": status, "retry_after_seconds": retry_after,
                             "input_count": count, "category": category})
        except Exception:
            log.warning("embedding error event could not be recorded")

    def _post_once(self, inputs: list[str]) -> list[list[float]]:
        body = json.dumps({"model": self.model, "input": inputs}, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request = Request(self.endpoint, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
        except HTTPError as exc:
            status = exc.code
            retry_after = self._retry_after(exc)
            category = ("rate_limited" if status == 429 else "timeout" if status == 408
                        else "upstream_unavailable" if status >= 500 else "authentication" if status in {401, 403}
                        else "invalid_request" if status == 400 else "http_error")
            raise _RequestFailure(category, status, retry_after, status in {408, 429} or status >= 500) from None
        except (TimeoutError, URLError, OSError):
            raise _RequestFailure("network_error", None, None, True) from None
        if len(raw) > 4 * 1024 * 1024:
            raise _RequestFailure("response_too_large", None, None, False)
        try:
            payload = json.loads(raw)
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, list) or len(data) != len(inputs):
                raise ValueError
            if any(not isinstance(item, dict) or type(item.get("index")) is not int for item in data):
                raise ValueError
            if sorted(item["index"] for item in data) != list(range(len(inputs))):
                raise ValueError
            vectors = []
            for item in sorted(data, key=lambda row: row["index"]):
                values = item.get("embedding")
                if not isinstance(values, list) or len(values) != self.dimension:
                    raise ValueError
                values = [float(value) for value in values]
                norm = math.sqrt(math.fsum(value * value for value in values))
                if norm <= 1e-12 or not all(math.isfinite(value) for value in values):
                    raise ValueError
                vectors.append([value / norm for value in values])
            return vectors
        except (ValueError, TypeError, KeyError, OverflowError):
            raise _RequestFailure("invalid_response", None, None, False) from None

    def _post(self, inputs: list[str], *, operation: str) -> list[list[float]]:
        if not inputs:
            return []
        if len(inputs) > self.MAX_BATCH_SIZE:
            raise ValueError("embedding batch cannot exceed 100 inputs")
        last: _RequestFailure | None = None
        for attempt in range(self.retries + 1):
            try:
                result = self._post_once(inputs)
                self.last_retry_attempts = attempt
                return result
            except _RequestFailure as exc:
                last = exc
                self._record_error(exc.category, exc.status, exc.retry_after, len(inputs), operation)
                if not exc.retryable or attempt >= self.retries:
                    self.last_retry_attempts = attempt
                    raise EmbeddingUnavailable(exc.category, retry_attempts=attempt,
                                               http_status=exc.status) from None
                base = min(self.backoff_seconds * (2 ** attempt), self.max_backoff_seconds)
                delay = exc.retry_after if exc.retry_after is not None else random_uniform(0.0, base)
                sleep(delay)
        assert last is not None
        raise EmbeddingUnavailable(last.category, retry_attempts=self.retries, http_status=last.status)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._post(list(texts), operation="DOCUMENT")

    def embed_query(self, text: str) -> list[float]:
        return self._post([text], operation="QUERY")[0]


class QwenEmbedder(GeminiEmbedder):
    """Qwen3 embeddings: raw documents and a retrieval instruction on queries only.

    Keep the input format in the config identity: instruction changes require re-indexing.
    """

    DEFAULT_DIMENSION = 1024
    PROVIDER = "qwen"
    INPUT_FORMAT = "qwen3-retrieval-v1"
    QUERY_INSTRUCTION = "Given a machine tool service complaint or technical question, retrieve relevant service cases and manual passages."

    @classmethod
    def from_env(cls, *, error_sink=None):
        base = os.getenv("QWEN_EMBEDDING_BASE_URL", "").strip()
        model = os.getenv("QWEN_EMBEDDING_MODEL", "qwen3-embedding-0.6b").strip()
        if not base or not model:
            raise ValueError("QWEN_EMBEDDING_BASE_URL and QWEN_EMBEDDING_MODEL must be configured")
        return cls(base, os.getenv("QWEN_EMBEDDING_API_KEY", ""), model,
                   dimension=int(os.getenv("QWEN_EMBEDDING_DIMENSION", str(cls.DEFAULT_DIMENSION))),
                   timeout=float(os.getenv("QWEN_EMBEDDING_TIMEOUT_SECONDS", "240")),
                   retries=int(os.getenv("QWEN_EMBEDDING_MAX_RETRIES", "2")),
                   backoff_seconds=3, max_backoff_seconds=30, error_sink=error_sink)

    def embed_query(self, text: str) -> list[float]:
        return self._post([f"Instruct: {self.QUERY_INSTRUCTION}\nQuery: {text}"], operation="QUERY")[0]


def configured_embedder(*, provider: str | None = None, error_sink=None) -> GeminiEmbedder:
    provider = (provider or os.getenv("RAG_EMBEDDING_PROVIDER", "gemini")).strip().lower()
    if provider not in {"gemini", "qwen"}:
        raise ValueError("embedding provider must be gemini or qwen")
    cls = QwenEmbedder if provider == "qwen" else GeminiEmbedder
    return cls.from_env(error_sink=error_sink)


class _RequestFailure(Exception):
    def __init__(self, category: str, status: int | None, retry_after: float | None, retryable: bool):
        self.category = category
        self.status = status
        self.retry_after = retry_after
        self.retryable = retryable

from __future__ import annotations

import json
from collections import deque
from typing import Any, Iterable, Iterator, Sequence

from app.agent_rag.db import pgvector_literal
from app.agent_rag.embedding import EmbeddingUnavailable, GeminiEmbedder


# Everything that gets embedded: manual pages and past service cases share rag_embedding by content hash.
_EMBEDDABLE = """(SELECT content_hash,content FROM rag_page WHERE content <> ''
                   UNION ALL SELECT content_hash,content FROM rag_case WHERE content <> '')"""


_SOURCES = {
    "all": _EMBEDDABLE,
    "pages": "(SELECT content_hash,content FROM rag_page WHERE content <> '')",
    "cases": "(SELECT content_hash,content FROM rag_case WHERE content <> '')",
}


def batches(values: Sequence[Any], size: int = 64) -> Iterator[list[Any]]:
    if not 1 <= size <= GeminiEmbedder.MAX_BATCH_SIZE:
        raise ValueError("embedding batch size must be between 1 and 100")
    for start in range(0, len(values), size):
        yield list(values[start:start + size])


def embedding_config_id(embedder: GeminiEmbedder) -> str:
    return embedder.config_id


def ensure_embedding_config(connection, embedder: GeminiEmbedder, *, activate: bool = False) -> str:
    identity = embedder.identity
    config_id = embedding_config_id(embedder)
    with connection.transaction():
        connection.execute(
            """INSERT INTO rag_embedding_config(config_id,provider,model,dimension,endpoint,input_format,active)
               VALUES (%s,%s,%s,%s,%s,%s,FALSE) ON CONFLICT(config_id) DO NOTHING""",
            (config_id, identity["provider"], identity["model"], identity["dimension"],
             identity["endpoint"], identity["input_format"]),
        )
        if activate:
            ready = connection.execute(
                f"""SELECT count(*) FROM (SELECT DISTINCT content_hash FROM {_EMBEDDABLE} u) p
                   WHERE NOT EXISTS (SELECT 1 FROM rag_embedding e WHERE e.config_id=%s
                                     AND e.content_hash=p.content_hash AND e.status='ready')""",
                (config_id,),
            ).fetchone()[0]
            if ready:
                raise RuntimeError(f"cannot activate embedding config; {ready} content hashes are not ready")
            connection.execute("UPDATE rag_embedding_config SET active=FALSE WHERE active=TRUE")
            connection.execute("UPDATE rag_embedding_config SET active=TRUE WHERE config_id=%s", (config_id,))
    return config_id


def index_embeddings(connection, embedder: GeminiEmbedder, *, batch_size: int = 64,
                     limit: int | None = None, only: str = "all") -> dict[str, int]:
    """Embed pending contents. `limit` caps this run (e.g. a small probe); a later run resumes the rest."""
    if not 1 <= batch_size <= GeminiEmbedder.MAX_BATCH_SIZE:
        raise ValueError("embedding batch size must be between 1 and 100")
    if limit is not None and limit < 1:
        raise ValueError("limit must be a positive number")
    if only not in _SOURCES:
        raise ValueError("only must be one of: " + ", ".join(_SOURCES))
    source = _SOURCES[only]
    config_id = ensure_embedding_config(connection, embedder)
    pending = connection.execute(
        f"""SELECT p.content_hash
           FROM {source} p
           GROUP BY p.content_hash
           HAVING NOT EXISTS (SELECT 1 FROM rag_embedding e WHERE e.config_id=%s
                              AND e.content_hash=p.content_hash AND e.status='ready')
           ORDER BY p.content_hash""",
        (config_id,),
    ).fetchall()
    if limit is not None:
        pending = pending[:limit]
    # Never hold a database transaction while making a remote embedding request.
    connection.commit()
    completed = failed = 0
    queue = deque(batches(pending, batch_size))
    while queue:
        batch = queue.popleft()
        hashes = [str(row[0]) for row in batch]
        # Only this batch's text is read; loading every pending page up front cost seconds per run.
        content_by_hash = dict(connection.execute(
            f"""SELECT p.content_hash,COALESCE(o.content,min(p.content))
                FROM {source} p LEFT JOIN rag_embedding_input_override o
                  ON o.config_id=%s AND o.content_hash=p.content_hash
                WHERE p.content_hash=ANY(%s) GROUP BY p.content_hash,o.content""",
            (config_id, hashes)).fetchall())
        connection.commit()
        texts = [str(content_by_hash[digest]) for digest in hashes]
        with connection.transaction():
            for digest in hashes:
                connection.execute(
                    """INSERT INTO rag_embedding(config_id,content_hash,status,embedding,attempts,last_error_category)
                       VALUES (%s,%s,'pending',NULL,0,NULL)
                       ON CONFLICT(config_id,content_hash) DO UPDATE SET status='pending',
                         last_error_category=NULL,updated_at=now() WHERE rag_embedding.status <> 'ready'""",
                    (config_id, digest),
                )
        try:
            vectors = embedder.embed_documents(texts)
            if len(vectors) != len(hashes):
                raise EmbeddingUnavailable("invalid_response")
        except EmbeddingUnavailable as exc:
            # Invalid input in one item must not block the rest of a batch. Never split quota/server errors.
            if exc.http_status == 400 and len(batch) > 1:
                middle = len(batch) // 2
                queue.appendleft(batch[middle:])
                queue.appendleft(batch[:middle])
                continue
            with connection.transaction():
                connection.execute(
                    """UPDATE rag_embedding SET status='failed',embedding=NULL,
                       attempts=attempts+%s,last_error_category=%s,updated_at=now()
                       WHERE config_id=%s AND content_hash=ANY(%s)""",
                    (max(1, exc.retry_attempts + 1), exc.category, config_id, hashes),
                )
            failed += len(hashes)
            continue
        with connection.transaction():
            for digest, vector in zip(hashes, vectors, strict=True):
                connection.execute(
                    """UPDATE rag_embedding SET status='ready',embedding=%s::vector,
                       attempts=attempts+%s,last_error_category=NULL,updated_at=now()
                       WHERE config_id=%s AND content_hash=%s""",
                    (pgvector_literal(vector), max(1, embedder.last_retry_attempts + 1), config_id, digest),
                )
        completed += len(hashes)
    remaining = connection.execute(
        f"""SELECT count(DISTINCT p.content_hash) FROM {source} p
           WHERE NOT EXISTS (SELECT 1 FROM rag_embedding e WHERE e.config_id=%s
                           AND e.content_hash=p.content_hash AND e.status='ready')""",
        (config_id,),
    ).fetchone()[0]
    return {"config_id": config_id, "completed": completed, "failed": failed, "remaining": remaining}

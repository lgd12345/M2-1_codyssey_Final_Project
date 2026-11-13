"""Read-only diagnosis of whether runtime embeddings and the active DB index agree.

Never calls an embedding server and never writes: switching models changes both the active
DB config and the runtime provider, and a half-switched state silently degrades to keyword search.
"""
from __future__ import annotations

_EMBEDDABLE = """(SELECT content_hash FROM rag_page WHERE content <> ''
                   UNION SELECT content_hash FROM rag_case WHERE content <> '')"""


def _coverage(connection, config_id: str) -> dict[str, int]:
    ready, missing = connection.execute(
        f"""SELECT count(*) FILTER (WHERE EXISTS (SELECT 1 FROM rag_embedding e WHERE e.config_id=%s
                      AND e.content_hash=p.content_hash AND e.status='ready')),
                   count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM rag_embedding e WHERE e.config_id=%s
                      AND e.content_hash=p.content_hash AND e.status='ready'))
            FROM {_EMBEDDABLE} p""", (config_id, config_id)).fetchone()
    return {"ready": ready, "missing": missing}


def embedding_readiness(connection, embedder) -> dict:
    expected = embedder.identity
    active = connection.execute(
        "SELECT config_id,provider,model,dimension,endpoint,input_format FROM rag_embedding_config WHERE active=TRUE"
    ).fetchone()
    own = _coverage(connection, embedder.config_id)
    report = {"status": "ready", "active_config_id": None, "embedder_config_id": embedder.config_id,
              "embedder_ready": own["ready"], "embedder_missing": own["missing"]}
    if not active:
        report["status"] = "not_indexed"
        return report
    report["active_config_id"] = str(active[0])
    actual = {"provider": active[1], "model": active[2], "dimension": active[3],
              "endpoint": active[4], "input_format": active[5]}
    if actual != expected:
        report["status"] = "config_mismatch"
    elif own["missing"]:
        report["status"] = "incomplete"
    return report

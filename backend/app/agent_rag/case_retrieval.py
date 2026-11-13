"""Hybrid search over past service cases: keyword + trigram + vector fused with reciprocal-rank fusion."""
from __future__ import annotations

from typing import Any, Callable, Sequence

from app.agent_rag.cases import normalize_part_no
from app.agent_rag.db import connect_database, pgvector_literal
from app.agent_rag.embedding import EmbeddingUnavailable, GeminiEmbedder
from app.agent_rag.preprocess import extract_query_identifiers, lexical_query, normalize_text
from app.agent_rag.retrieval import RRF_K, _query_vector

BRIEF_WEIGHT = 0.7  # a one-line resolution is weaker evidence than a described procedure
# Hangul bigrams such as "발생" or "합니" occur in most cases; an OR query over them matches nearly every row
# and ranks by noise. Terms present in more than this share of cases are ignored for keyword search.
# Measured on self-retrieval of 60 complaints (MRR / ms per query): no filter 0.58|0.38 / 447-1883ms,
# 20% + 48 terms 0.56|0.45 / 232-489ms, 5% + 24 terms 0.44|0.35 / 37-49ms. Filtering harder is faster but
# loses recall, so 20% is the default.
MAX_TERM_SHARE = 0.20
MIN_DF_CEILING = 20
MAX_QUERY_TERMS = 48
_df_cache: dict[str, Any] = {"fingerprint": None, "df": {}, "total": 0}


def _term_stats(connection) -> tuple[dict[str, int], int]:
    """Document frequency per lexeme, recomputed only when the case table changed."""
    fingerprint = tuple(connection.execute("SELECT count(*),coalesce(max(id),0) FROM rag_case").fetchone())
    if _df_cache["fingerprint"] != fingerprint:
        rows = connection.execute("SELECT word,ndoc FROM ts_stat('SELECT search_vector FROM rag_case')").fetchall()
        _df_cache.update(fingerprint=fingerprint, df={word: int(ndoc) for word, ndoc in rows},
                         total=int(fingerprint[0]))
    return _df_cache["df"], _df_cache["total"]


def selective_terms(connection, query: str) -> list[str]:
    """Query lexemes that exist in the corpus and are not boilerplate, rarest first."""
    df, total = _term_stats(connection)
    ceiling = max(MIN_DF_CEILING, int(total * MAX_TERM_SHARE))
    terms = [term for term in lexical_query(query).split(" | ") if term]
    known = [term for term in terms if 0 < df.get(term, 0)]
    useful = [term for term in known if df[term] <= ceiling]
    if not useful and known:  # every term is common: keep the rarest few rather than return nothing
        useful = sorted(known, key=lambda term: df[term])[:5]
    return sorted(useful, key=lambda term: df[term])[:MAX_QUERY_TERMS]
_COLUMNS = """c.id,c.fsr_no,c.duplicate_fsr_nos,c.machine,c.warranty,c.repair_type,c.registered_on,
              c.symptom_major,c.symptom_mid,c.symptom_minor,c.complaint,c.resolution,
              c.requested_part_no,c.requested_part_name,c.replacement_part_no,c.replacement_part_name,
              c.quality,c.content_hash"""
_MACHINE = "(cardinality(%s::text[])=0 OR c.machine=ANY(%s))"


def _row_to_case(row: tuple) -> dict[str, Any]:
    (_id, fsr_no, duplicates, machine, warranty, repair_type, registered_on, major, mid, minor, complaint,
     resolution, req_no, req_name, alt_no, alt_name, quality, content_hash) = row[:18]
    return {"fsr_no": fsr_no, "machine": machine, "warranty": warranty, "repair_type": repair_type,
            "registered_on": registered_on.isoformat() if registered_on else None,
            "symptom": [value for value in (major, mid, minor) if value],
            "complaint": complaint, "resolution": resolution,
            "requested_part": {"part_no": req_no, "name": req_name} if (req_no or req_name) else None,
            "replacement_part": {"part_no": alt_no, "name": alt_name} if (alt_no or alt_name) else None,
            "resolution_detail": quality, "same_case_count": 1 + len(duplicates or []),
            "content_hash": content_hash}


def search_cases(query: str, *, machines: Sequence[str] | None = None, top_k: int = 6,
                 embedder: GeminiEmbedder | None = None, connection=None, database_url: str | None = None,
                 connect: Callable[..., Any] = connect_database) -> dict[str, Any]:
    query = normalize_text(query)
    if not query:
        return {"query": query, "results": [], "search_status": {"keyword": "empty_query", "vector": {"status": "not_requested"}}}
    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20")
    machine_args = list(machines or [])
    limit = max(30, top_k * 4)
    own = connection is None
    connection = connection or connect(database_url)
    vector_status: dict[str, Any] = {"status": "not_configured"}
    legs: dict[str, list[tuple]] = {}
    try:
        part_nos = [normalize_part_no(item.raw) for item in extract_query_identifiers(query)
                    if item.kind == "part_no"]
        legs["exact"] = connection.execute(
            f"SELECT {_COLUMNS} FROM rag_case c WHERE c.part_numbers && %s::text[] AND {_MACHINE} "
            "ORDER BY c.registered_on DESC NULLS LAST,c.id LIMIT %s",
            (part_nos, machine_args, machine_args, limit)).fetchall() if part_nos else []
        terms = " | ".join(selective_terms(connection, query))
        legs["keyword"] = connection.execute(
            f"SELECT {_COLUMNS} FROM rag_case c WHERE c.search_vector @@ to_tsquery('simple',%s) AND {_MACHINE} "
            "ORDER BY ts_rank_cd(c.search_vector,to_tsquery('simple',%s)) DESC,c.id LIMIT %s",
            (terms, machine_args, machine_args, terms, limit)).fetchall() if terms else []
        if embedder is not None:
            active = connection.execute(
                "SELECT config_id,provider,model,dimension,endpoint,input_format "
                "FROM rag_embedding_config WHERE active=TRUE").fetchone()
            if not active:
                vector_status = {"status": "not_indexed", "code": "no_active_embedding_config"}
            elif {"provider": active[1], "model": active[2], "dimension": active[3], "endpoint": active[4],
                  "input_format": active[5]} != embedder.identity:
                vector_status = {"status": "unavailable", "code": "embedding_config_mismatch"}
            else:
                try:
                    vector = _query_vector(connection, embedder, query)
                    legs["vector"] = connection.execute(
                        f"SELECT {_COLUMNS} FROM rag_case c "
                        "JOIN rag_embedding e ON e.content_hash=c.content_hash AND e.config_id=%s AND e.status='ready' "
                        f"WHERE {_MACHINE} ORDER BY e.embedding <=> %s::vector,c.id LIMIT %s",
                        (str(active[0]), machine_args, machine_args, pgvector_literal(vector), limit)).fetchall()
                    vector_status = {"status": "ok", "model": embedder.model,
                                     "retry_attempts": embedder.last_retry_attempts}
                except EmbeddingUnavailable as exc:
                    vector_status = {"status": "unavailable", "code": exc.category,
                                     "http_status": exc.http_status, "retry_attempts": exc.retry_attempts}
        fused: dict[str, dict[str, Any]] = {}
        for leg, rows in legs.items():
            for rank, row in enumerate(rows, 1):
                entry = fused.setdefault(row[1], {"case": _row_to_case(row), "score": 0.0, "ranks": {}})
                entry["ranks"][leg] = rank
                entry["score"] += 1.0 if leg == "exact" else 1.0 / (RRF_K + rank)
        for entry in fused.values():
            if entry["case"]["resolution_detail"] == "brief":
                entry["score"] *= BRIEF_WEIGHT
        ranked = sorted(fused.values(), key=lambda item: item["score"], reverse=True)[:top_k]
        results = [{**item["case"], "score": item["score"], "ranks": item["ranks"]} for item in ranked]
        for item in results:
            item.pop("content_hash", None)
        return {"query": query, "results": results,
                "search_status": {"exact_part_no": "matched" if legs["exact"] else
                                                   "no_match" if part_nos else "not_detected",
                                  "keyword": "ok" if legs["keyword"] else "no_match",
                                  "vector": vector_status}}
    finally:
        if own:
            try:
                connection.commit()
            except Exception:
                connection.rollback()
            connection.close()

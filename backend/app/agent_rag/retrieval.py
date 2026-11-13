from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Callable, Sequence
from uuid import uuid4

from app.agent_rag.db import connect_database, pgvector_literal
from app.agent_rag.embedding import EmbeddingUnavailable, GeminiEmbedder
from app.agent_rag.preprocess import extract_query_identifiers, lexical_query, normalize_text
from app.agent_rag.tables import table_evidence

RRF_K = 60
_IDENTIFIER_NORMALIZE = re.compile(r"\s+")
# A part number and a drawing number are the same family of code (2064-01-101-01 / 2064-05-003-03): a caller
# that cannot tell which one it holds must find either, still by exact match only.
CODE_FAMILY = ("part_no", "drawing_no")


def kinds_for(kind: str | None) -> list[str] | None:
    if kind is None:
        return None
    return list(CODE_FAMILY) if kind in CODE_FAMILY else [kind]


@dataclass
class Candidate:
    content_hash: str
    score: float = 0.0
    ranks: dict[str, int] = field(default_factory=dict)
    pages: list[dict[str, Any]] = field(default_factory=list)


def normalize_identifier(value: str) -> str:
    return _IDENTIFIER_NORMALIZE.sub("", normalize_text(value)).upper()


def lookup_identifier(value: str, *, kind: str | None = None, connection=None,
                      database_url: str | None = None, connect: Callable[..., Any] = connect_database) -> dict[str, Any]:
    detected = extract_query_identifiers(value)
    wanted = kinds_for(kind)
    candidates = [item for item in detected if wanted is None or item.kind in wanted]
    if len(candidates) == 1:
        normalized = candidates[0].normalized
    elif len(candidates) > 1:
        return {"found": False, "value": normalize_identifier(value), "matches": [],
                "status": "ambiguous_identifier_input"}
    elif detected:
        return {"found": False, "value": normalize_identifier(value), "matches": [],
                "status": "identifier_kind_mismatch"}
    else:
        normalized = normalize_identifier(value)
    if not normalized:
        return {"found": False, "value": normalized, "matches": []}
    own_connection = connection is None
    connection = connection or connect(database_url)
    try:
        rows = connection.execute(
            """SELECT i.kind,i.normalized,i.raw,p.pdf_page,p.printed_page,p.page_class,p.verification,
                      p.content,d.source_sha256,d.title,a.machine,a.manufacturer
               FROM rag_identifier i JOIN rag_page p ON p.id=i.page_id
               JOIN rag_document d ON d.source_sha256=p.source_sha256
               LEFT JOIN rag_source_alias a ON a.source_sha256=d.source_sha256
               WHERE i.normalized=%s AND (%s::text[] IS NULL OR i.kind=ANY(%s))
               ORDER BY i.kind,d.title,p.pdf_page""",
            (normalized, wanted, wanted),
        ).fetchall()
        matches = []
        seen = set()
        for row in rows:
            (found_kind, found_value, raw, page, printed, page_class, verification, content,
             digest, title, machine, manufacturer) = row
            key = (found_kind, digest, page)
            if key in seen:
                continue
            seen.add(key)
            matches.append({"kind": found_kind, "normalized": found_value, "raw": raw,
                            "document_sha256": digest, "title": title, "pdf_page": page,
                            "printed_page": printed, "page_class": page_class,
                            "verification": verification, "text_origin": "ocr_or_text_extraction",
                            "content": content, "machine": machine, "manufacturer": manufacturer,
                            "table_evidence": table_evidence(content, query=value)})
        return {"found": bool(matches), "value": normalized, "matches": matches}
    finally:
        if own_connection:
            connection.close()


def _machine_filter(machines: Sequence[str] | None) -> list[str]:
    return list(machines or [])


def _fetch_rows(connection, *, machines: Sequence[str] | None,
                lexical: str | None = None, query_text: str | None = None,
                query_vector: list[float] | None = None, config_id: str | None = None, limit: int = 50):
    machines_arg = _machine_filter(machines)
    base_select = """SELECT p.id,p.content_hash,p.content,p.pdf_page,p.printed_page,p.page_class,p.verification,
                           p.source_sha256,d.title,a.machine,a.manufacturer"""
    base_from = """ FROM rag_page p JOIN rag_document d USING(source_sha256)
                      LEFT JOIN LATERAL (SELECT min(machine) AS machine,min(manufacturer) AS manufacturer
                                         FROM rag_source_alias WHERE source_sha256=d.source_sha256) a ON TRUE
                      WHERE p.search_text <> '' AND (cardinality(%s::text[])=0 OR EXISTS
                        (SELECT 1 FROM rag_source_alias af WHERE af.source_sha256=d.source_sha256 AND af.machine=ANY(%s)))"""
    params: list[Any] = [machines_arg, machines_arg]
    rows: dict[str, list[tuple]] = {}
    if lexical:
        # Preserve database exception types so the tool layer can classify operational failures.
        ts_rows = connection.execute(
            base_select + base_from + " AND p.search_vector @@ to_tsquery('simple',%s) "
            "ORDER BY ts_rank_cd(p.search_vector,to_tsquery('simple',%s)) DESC,p.id LIMIT %s",
            (*params, lexical, lexical, limit),
        ).fetchall()
        rows["keyword"] = ts_rows
    if query_text and len(query_text.strip()) >= 3:
        trigram_rows = connection.execute(
            base_select + base_from + " AND p.search_text %% %s "
            "ORDER BY similarity(p.search_text,%s) DESC,p.id LIMIT %s",
            (*params, query_text, query_text, limit),
        ).fetchall()
        rows["trigram"] = trigram_rows
    if query_vector is not None and config_id:
        vector_rows = connection.execute(
            """SELECT p.id,p.content_hash,p.content,p.pdf_page,p.printed_page,p.page_class,p.verification,
                      p.source_sha256,d.title,a.machine,a.manufacturer,
                      e.embedding <=> %s::vector AS distance
               FROM rag_page p JOIN rag_document d USING(source_sha256)
               JOIN rag_embedding e ON e.content_hash=p.content_hash AND e.config_id=%s AND e.status='ready'
               LEFT JOIN LATERAL (SELECT min(machine) AS machine,min(manufacturer) AS manufacturer
                                  FROM rag_source_alias WHERE source_sha256=d.source_sha256) a ON TRUE
               WHERE p.search_text <> '' AND (cardinality(%s::text[])=0 OR EXISTS
                 (SELECT 1 FROM rag_source_alias af WHERE af.source_sha256=d.source_sha256 AND af.machine=ANY(%s)))
               ORDER BY distance,p.id LIMIT %s""",
            (pgvector_literal(query_vector), config_id, machines_arg, machines_arg, limit),
        ).fetchall()
        rows["vector"] = vector_rows
    return rows


def _fetch_exact_rows(connection, query: str, *, machines: Sequence[str] | None) -> list[tuple]:
    machine_args = _machine_filter(machines)
    found: list[tuple] = []
    for identifier in extract_query_identifiers(query):
        rows = connection.execute(
            """SELECT p.id,p.content_hash,p.content,p.pdf_page,p.printed_page,p.page_class,p.verification,
                      p.source_sha256,d.title,a.machine,a.manufacturer
               FROM rag_identifier i JOIN rag_page p ON p.id=i.page_id
               JOIN rag_document d ON d.source_sha256=p.source_sha256
               LEFT JOIN LATERAL (SELECT min(machine) AS machine,min(manufacturer) AS manufacturer
                                  FROM rag_source_alias WHERE source_sha256=d.source_sha256) a ON TRUE
               WHERE i.kind=ANY(%s) AND i.normalized=%s AND p.search_text<>''
                 AND (cardinality(%s::text[])=0 OR EXISTS
                   (SELECT 1 FROM rag_source_alias af WHERE af.source_sha256=d.source_sha256 AND af.machine=ANY(%s)))
               ORDER BY d.title,p.pdf_page""",
            (kinds_for(identifier.kind), identifier.normalized, machine_args, machine_args),
        ).fetchall()
        found.extend(rows)
    return found


def _query_vector(connection, embedder: GeminiEmbedder, query: str) -> list[float]:
    cache_key = hashlib.sha256(f"{embedder.config_id}\0{query}".encode("utf-8")).hexdigest()
    cached = connection.execute(
        "SELECT embedding::text FROM rag_query_embedding_cache WHERE cache_key=%s AND expires_at>now()",
        (cache_key,),
    ).fetchone()
    if cached:
        try:
            return [float(value) for value in json.loads(cached[0])]
        except (ValueError, TypeError, json.JSONDecodeError):
            connection.execute("DELETE FROM rag_query_embedding_cache WHERE cache_key=%s", (cache_key,))
    # Release the read transaction before waiting on the remote embedding proxy.
    connection.commit()
    vector = embedder.embed_query(query)
    connection.execute(
        """INSERT INTO rag_query_embedding_cache(cache_key,config_id,embedding,expires_at)
           VALUES (%s,%s,%s::vector,now()+interval '24 hours')
           ON CONFLICT(cache_key) DO UPDATE SET embedding=EXCLUDED.embedding,
             expires_at=EXCLUDED.expires_at,created_at=now()""",
        (cache_key, embedder.config_id, pgvector_literal(vector)),
    )
    return vector


def _candidate_groups(connection, legs: dict[str, list[tuple]], *, machines: Sequence[str] | None, top_k: int) -> list[Candidate]:
    grouped: dict[str, Candidate] = {}
    for leg, rows in legs.items():
        # Keep the strongest occurrence of identical text per leg so repeated manuals do not dominate the rank.
        best_rank: dict[str, tuple[int, tuple]] = {}
        for rank, row in enumerate(rows, 1):
            content_hash = row[1]
            if content_hash not in best_rank:
                best_rank[content_hash] = (rank, row)
        for content_hash, (rank, row) in best_rank.items():
            candidate = grouped.setdefault(content_hash, Candidate(content_hash))
            candidate.ranks[leg] = rank
            candidate.score += 1.0 if leg == "exact" else 1.0 / (RRF_K + rank)

    if not grouped:
        return []
    digests = list(grouped)
    machine_args = _machine_filter(machines)
    page_rows = connection.execute(
        """SELECT p.id,p.content_hash,p.content,p.pdf_page,p.printed_page,p.page_class,p.verification,
                  p.source_sha256,d.title,a.machine,a.manufacturer
           FROM rag_page p JOIN rag_document d USING(source_sha256)
           LEFT JOIN LATERAL (SELECT min(machine) AS machine,min(manufacturer) AS manufacturer
                              FROM rag_source_alias WHERE source_sha256=d.source_sha256) a ON TRUE
           WHERE p.content_hash=ANY(%s) AND (cardinality(%s::text[])=0 OR EXISTS
             (SELECT 1 FROM rag_source_alias af WHERE af.source_sha256=d.source_sha256 AND af.machine=ANY(%s)))
           ORDER BY p.pdf_page,d.title""",
        (digests, machine_args, machine_args),
    ).fetchall()
    refs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    pages_by_id: dict[int, dict[str, Any]] = {}
    for row in page_rows:
        page_id, content_hash, content, page_no, printed, page_class, verification, digest, title, machine, manufacturer = row
        page = {"page_id": page_id, "document_sha256": digest, "title": title,
                "pdf_page": page_no, "printed_page": printed, "page_class": page_class,
                "verification": verification, "text_origin": "ocr_or_text_extraction", "machine": machine,
                "manufacturer": manufacturer, "content": content}
        refs[content_hash].append(page)
        pages_by_id[page_id] = page
    ids = list(pages_by_id)
    related: dict[int, list[dict[str, Any]]] = defaultdict(list)
    if ids:
        link_rows = connection.execute(
            """SELECT l.from_page_id,l.to_page_id,p.pdf_page,p.printed_page,p.page_class,p.source_sha256,d.title
               FROM rag_page_link l JOIN rag_page p ON p.id=l.to_page_id
               JOIN rag_document d USING(source_sha256) WHERE l.from_page_id=ANY(%s)
               UNION ALL
               SELECT l.to_page_id,l.from_page_id,p.pdf_page,p.printed_page,p.page_class,p.source_sha256,d.title
               FROM rag_page_link l JOIN rag_page p ON p.id=l.from_page_id
               JOIN rag_document d USING(source_sha256) WHERE l.to_page_id=ANY(%s)""",
            (ids, ids),
        ).fetchall()
        for owner, target, page_no, printed, page_class, digest, title in link_rows:
            related[owner].append({"document_sha256": digest, "title": title,
                                   "pdf_page": page_no, "printed_page": printed, "page_class": page_class})
    for content_hash, candidate in grouped.items():
        candidate.pages = refs.get(content_hash, [])
        for page in candidate.pages:
            page["related_pages"] = related.get(page["page_id"], [])
    return sorted(grouped.values(), key=lambda candidate: candidate.score, reverse=True)[:top_k]


def search_manual(query: str, *, machines: Sequence[str] | None = None,
                  top_k: int = 8, embedder: GeminiEmbedder | None = None, connection=None,
                  database_url: str | None = None, connect: Callable[..., Any] = connect_database) -> dict[str, Any]:
    query = normalize_text(query)
    if not query:
        return {"query": query, "results": [], "search_status": {
            "keyword": "empty_query", "trigram": "empty_query", "vector": {"status": "not_requested"}}}
    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20")
    own_connection = connection is None
    connection = connection or connect(database_url)
    vector_status: dict[str, Any] = {"status": "not_configured"}
    try:
        detected_identifiers = extract_query_identifiers(query)
        if detected_identifiers:
            # Identifier-shaped queries are exact-only: do not let lexical/vector similarity substitute a nearby code.
            legs = {"exact": _fetch_exact_rows(connection, query, machines=machines),
                    "keyword": [], "trigram": []}
            vector_status = {"status": "bypassed_exact_identifier"}
        else:
            query_terms = lexical_query(query)
            legs = _fetch_rows(connection, machines=machines,
                               lexical=query_terms or None, query_text=query, limit=max(30, top_k * 4))
            legs["exact"] = []
            if "keyword" not in legs:
                legs["keyword"] = []
            if "trigram" not in legs:
                legs["trigram"] = []
        if embedder is not None and not detected_identifiers:
            active = connection.execute(
                "SELECT config_id,provider,model,dimension,endpoint,input_format FROM rag_embedding_config WHERE active=TRUE"
            ).fetchone()
            if not active:
                vector_status = {"status": "not_indexed", "code": "no_active_embedding_config"}
            else:
                config_id = str(active[0])
                expected = embedder.identity
                actual = {"provider": active[1], "model": active[2], "dimension": active[3],
                          "endpoint": active[4], "input_format": active[5]}
                if actual != expected:
                    vector_status = {"status": "unavailable", "code": "embedding_config_mismatch"}
                else:
                    try:
                        vector = _query_vector(connection, embedder, query)
                        legs["vector"] = _fetch_rows(connection, machines=machines,
                                                      query_vector=vector, config_id=config_id,
                                                      limit=max(30, top_k * 4)).get("vector", [])
                        vector_status = {"status": "ok", "model": embedder.model,
                                         "dimension": embedder.dimension,
                                         "retry_attempts": embedder.last_retry_attempts}
                    except EmbeddingUnavailable as exc:
                        vector_status = {"status": "unavailable", "code": exc.category,
                                         "http_status": exc.http_status,
                                         "retry_attempts": exc.retry_attempts}
        candidates = _candidate_groups(connection, legs, machines=machines, top_k=top_k)
        results = []
        for candidate in candidates:
            pages = candidate.pages
            if not pages:
                continue
            results.append({"content_hash": candidate.content_hash, "content": pages[0]["content"],
                            "score": candidate.score, "ranks": candidate.ranks,
                            "table_evidence": table_evidence(pages[0]["content"], query=query),
                            "sources": pages})
        return {"query": query, "results": results,
                "search_status": {"exact_identifier": "matched" if legs["exact"] else
                                                       "no_match" if detected_identifiers else "not_detected",
                                  "keyword": "ok" if legs["keyword"] else "no_match",
                                  "trigram": "ok" if legs["trigram"] else "no_match",
                                  "vector": vector_status}}
    finally:
        if own_connection:
            try:
                connection.commit()
            except Exception:
                connection.rollback()
            connection.close()

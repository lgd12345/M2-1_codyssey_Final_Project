"""Registered-document overview for the test screen. Counts and names only: never server file locations."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.deps import database, require_operator
from app.auth.service import SessionInfo

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

LIST_SQL = """
SELECT d.source_sha256, d.title, d.page_count,
       COALESCE((SELECT array_agg(DISTINCT a.machine ORDER BY a.machine)
                 FROM rag_source_alias a WHERE a.source_sha256 = d.source_sha256), '{}'),
       (SELECT min(a.manufacturer) FROM rag_source_alias a WHERE a.source_sha256 = d.source_sha256),
       (SELECT count(*) FROM rag_page p WHERE p.source_sha256 = d.source_sha256 AND p.content <> ''),
       (SELECT count(*) FROM rag_page p WHERE p.source_sha256 = d.source_sha256 AND p.content <> ''
          AND EXISTS (SELECT 1 FROM rag_embedding e WHERE e.content_hash = p.content_hash AND e.status = 'ready'))
FROM rag_document d ORDER BY d.title, d.source_sha256
"""


@router.get("")
def list_documents(_session: SessionInfo = Depends(require_operator)):
    with database() as connection:
        rows = connection.execute(LIST_SQL).fetchall()
        active = connection.execute("SELECT EXISTS (SELECT 1 FROM rag_embedding_config WHERE active)").fetchone()[0]
    documents = [{
        "id": row[0][:12], "title": row[1], "page_count": row[2],
        "machines": list(row[3]), "manufacturer": row[4], "searchable_pages": row[5], "embedded_pages": row[6],
    } for row in rows]
    return {
        "total": len(documents),
        "page_count": sum(d["page_count"] for d in documents),
        "searchable_pages": sum(d["searchable_pages"] for d in documents),
        "embedded_pages": sum(d["embedded_pages"] for d in documents),
        "vector_search": "active" if active else "inactive",
        "documents": documents,
    }

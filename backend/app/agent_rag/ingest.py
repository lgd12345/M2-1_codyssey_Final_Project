from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable

from psycopg.types.json import Jsonb

from app.agent_rag.corpus import CorpusDocument, infer_machine, infer_manufacturer, load_manifest
from app.agent_rag.db import connect_database
from app.agent_rag.preprocess import extract_identifiers, find_drawing_links, lexical_text


@dataclass(frozen=True)
class IngestSummary:
    documents: int
    pages: int
    identifiers: int
    links: int


def _verification(value: str) -> str:
    return value if value in {"verified", "corrected", "needs_review", "unverified"} else "unverified"


def ingest_documents(documents: list[CorpusDocument], *, connection: Any) -> IngestSummary:
    page_count = identifier_count = link_count = 0
    with connection.transaction():
        for document in documents:
            connection.execute(
                """INSERT INTO rag_document(source_sha256,title,page_count,pdf_path,metadata)
                   VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT(source_sha256) DO UPDATE SET title=EXCLUDED.title,page_count=EXCLUDED.page_count,
                     pdf_path=EXCLUDED.pdf_path,metadata=EXCLUDED.metadata""",
                (document.sha256, document.title, document.page_count,
                 str(document.pdf_path), Jsonb({"source_path": document.source_path})),
            )
            for alias in document.aliases:
                connection.execute(
                    """INSERT INTO rag_source_alias(source_sha256,source_path,machine,manufacturer)
                       VALUES (%s,%s,%s,%s) ON CONFLICT(source_sha256,source_path) DO UPDATE
                       SET machine=EXCLUDED.machine,manufacturer=EXCLUDED.manufacturer""",
                    (document.sha256, alias, infer_machine(alias), infer_manufacturer(alias)),
                )

            active_pages: list[int] = []
            page_ids: dict[int, int] = {}
            for page in document.pages:
                active_pages.append(page.pdf_page)
                content = page.content
                search_text = lexical_text(content)
                row = connection.execute(
                    """INSERT INTO rag_page(source_sha256,pdf_page,printed_page,page_class,content,search_text,
                           content_hash,verification,route,flags)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT(source_sha256,pdf_page) DO UPDATE SET printed_page=EXCLUDED.printed_page,
                         page_class=EXCLUDED.page_class,content=EXCLUDED.content,search_text=EXCLUDED.search_text,
                         content_hash=EXCLUDED.content_hash,verification=EXCLUDED.verification,
                         route=EXCLUDED.route,flags=EXCLUDED.flags
                       RETURNING id""",
                    (document.sha256, page.pdf_page, page.printed_page, page.page_class, content, search_text,
                     page.content_hash, _verification(page.verification), page.route, Jsonb(list(page.flags))),
                ).fetchone()
                page_ids[page.pdf_page] = int(row[0])
                page_count += 1
                connection.execute("DELETE FROM rag_identifier WHERE page_id = %s", (row[0],))
                for identifier in extract_identifiers(content):
                    connection.execute(
                        """INSERT INTO rag_identifier(page_id,kind,normalized,raw) VALUES (%s,%s,%s,%s)
                           ON CONFLICT(page_id,kind,normalized) DO NOTHING""",
                        (row[0], identifier.kind, identifier.normalized, identifier.raw),
                    )
                    identifier_count += 1

            if active_pages:
                connection.execute(
                    "DELETE FROM rag_page WHERE source_sha256 = %s AND NOT (pdf_page = ANY(%s))",
                    (document.sha256, active_pages),
                )
            connection.execute(
                "DELETE FROM rag_page_link l USING rag_page p WHERE l.from_page_id=p.id AND p.source_sha256=%s",
                (document.sha256,),
            )
            for table_page, drawing_page in find_drawing_links([
                {"pdf_page": page.pdf_page, "page_class": page.page_class} for page in document.pages
            ]):
                if table_page in page_ids and drawing_page in page_ids:
                    connection.execute(
                        "INSERT INTO rag_page_link(from_page_id,to_page_id,relation) VALUES (%s,%s,'parts_drawing') ON CONFLICT DO NOTHING",
                        (page_ids[table_page], page_ids[drawing_page]),
                    )
                    link_count += 1
    return IngestSummary(len(documents), page_count, identifier_count, link_count)


def ingest_corpus(corpus_dir: str | Path, *, database_url: str | None = None,
                  connect: Callable[..., Any] = connect_database) -> IngestSummary:
    documents = load_manifest(corpus_dir)
    connection = connect(database_url)
    try:
        return ingest_documents(documents, connection=connection)
    finally:
        connection.close()

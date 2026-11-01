"""The registered-document list shown on the test screen: login required, counts only, no server paths."""
import os
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict

from app.agent_rag.corpus import CorpusDocument, CorpusPage
from app.agent_rag.ingest import ingest_documents
from app.agent_rag.preprocess import prepare_page_text, stable_content_hash
from scripts.migrate import apply_migrations

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="isolated TEST_DATABASE_URL not configured")
PASSWORD = "correct-horse-battery"
SERVER_PATH = "/srv/secret-corpus/manual.pdf"


@pytest.fixture
def db(monkeypatch):
    if not conninfo_to_dict(DATABASE_URL).get("dbname", "").endswith("_test"):
        raise ValueError("TEST_DATABASE_URL must point to an isolated _test database")
    apply_migrations(DATABASE_URL)
    monkeypatch.setenv("RAG_DATABASE_URL", DATABASE_URL)
    connection = psycopg.connect(DATABASE_URL)
    clear = "TRUNCATE app_user, app_login_failure, rag_document, rag_embedding_config CASCADE"
    connection.execute(clear)
    connection.commit()
    yield connection
    connection.rollback()
    connection.execute(clear)
    connection.commit()
    connection.close()


def page(number, page_class, text):
    content = prepare_page_text(text, page_class=page_class)
    return CorpusPage(number, None, page_class, content, stable_content_hash(content), "verified", None, ())


def document(sha, machine, title, pages):
    path = f"/raw_files/{machine}/1. FANUC/{title}.pdf"
    return CorpusDocument(sha, title, path, (path,), Path(SERVER_PATH), len(pages), machine, "FANUC", tuple(pages))


def login(db):
    from app.auth.service import create_user
    from app.main import app
    create_user(db, "alice", PASSWORD)
    db.commit()
    client = TestClient(app)
    client.post("/api/v1/auth/login", json={"login_id": "alice", "password": PASSWORD}, headers={"Origin": "http://testserver"})
    return client


def test_anonymous_users_cannot_list_documents(db):
    from app.main import app
    assert TestClient(app).get("/api/v1/documents").status_code == 401


def test_lists_registered_documents_with_page_and_vector_counts(db):
    ingest_documents([
        document("a" * 64, "F400", "Troubleshooting", [
            page(1, "text", "서보모터 과열 알람 설명입니다."), page(2, "toc_index", "목차"), page(3, "blank_cover", "")]),
        document("b" * 64, "F500", "Parts list", [page(1, "table", "| NO. | PART NO. |\n| --- | --- |\n| 1 | ABC-12-3456 |")]),
    ], connection=db)
    db.commit()
    body = login(db).get("/api/v1/documents").json()
    assert body["total"] == 2 and body["vector_search"] == "inactive"
    assert [d["title"] for d in body["documents"]] == ["Parts list", "Troubleshooting"]
    trouble = next(d for d in body["documents"] if d["title"] == "Troubleshooting")
    assert (trouble["machines"], trouble["manufacturer"]) == (["F400"], "FANUC")
    assert "document_kind" not in trouble      # a guess from file names; not part of the document model
    assert (trouble["page_count"], trouble["searchable_pages"], trouble["embedded_pages"]) == (3, 1, 0)
    assert body["searchable_pages"] == 2 and body["embedded_pages"] == 0
    assert trouble["id"] == "a" * 12


def test_embedding_progress_and_activation_are_reported(db):
    ingest_documents([document("a" * 64, "F400", "Manual", [page(1, "text", "첫 페이지 본문입니다."),
                                                                             page(2, "text", "둘째 페이지 본문입니다.")])], connection=db)
    db.execute("INSERT INTO rag_embedding_config(config_id,provider,model,dimension,endpoint,input_format,active) "
               "VALUES ('c1','gemini','m',3072,'https://x/v1/embeddings','raw-v1',TRUE)")
    first = db.execute("SELECT content_hash FROM rag_page WHERE pdf_page=1").fetchone()[0]
    db.execute("INSERT INTO rag_embedding(config_id,content_hash,status,embedding,attempts) "
               "VALUES ('c1',%s,'ready',%s::vector(3072),1)", (first, "[" + ",".join(["1"] + ["0"] * 3071) + "]"))
    db.commit()
    body = login(db).get("/api/v1/documents").json()
    assert body["vector_search"] == "active"
    assert (body["documents"][0]["searchable_pages"], body["documents"][0]["embedded_pages"]) == (2, 1)


def test_server_file_locations_are_never_exposed(db):
    ingest_documents([document("a" * 64, "F400", "Manual", [page(1, "text", "안전 장치 설명 본문입니다.")])], connection=db)
    db.commit()
    response = login(db).get("/api/v1/documents")
    assert SERVER_PATH not in response.text and "pdf_path" not in response.text and "raw_files" not in response.text

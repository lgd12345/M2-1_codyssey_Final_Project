import hashlib
import os
from pathlib import Path

import pytest

from app.agent_rag.corpus import CorpusDocument, CorpusPage
from app.agent_rag.ingest import ingest_documents
from app.agent_rag.embedding import EmbeddingUnavailable
from app.agent_rag.embedding_index import ensure_embedding_config, index_embeddings
from app.agent_rag.retrieval import lookup_identifier, search_manual
from scripts.migrate import apply_migrations

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="isolated TEST_DATABASE_URL not configured")


@pytest.fixture
def test_db():
    from psycopg.conninfo import conninfo_to_dict
    database_name = conninfo_to_dict(DATABASE_URL).get("dbname", "")
    if not database_name.endswith("_test"):
        raise ValueError("TEST_DATABASE_URL must point to an isolated database ending in _test")
    apply_migrations(DATABASE_URL)
    import psycopg
    connection = psycopg.connect(DATABASE_URL)
    _clear_test_data(connection)
    try:
        yield connection
    finally:
        connection.rollback()
        _clear_test_data(connection)
        connection.close()


def _clear_test_data(connection):
    connection.execute("TRUNCATE rag_document,rag_embedding_api_error,rag_retrieval_run CASCADE")
    connection.execute("TRUNCATE rag_embedding_config CASCADE")
    connection.commit()


def _page(number, page_class, text, printed=None, verification="verified"):
    from app.agent_rag.preprocess import prepare_page_text, stable_content_hash
    content = prepare_page_text(text, page_class=page_class)
    return CorpusPage(number, printed, page_class, content, stable_content_hash(content), verification, "deterministic", ())


def _document(sha, machine, pages, title="manual"):
    return CorpusDocument(sha, title, f"/raw_files/{machine}/1. FANUC/{title}.pdf",
                          (f"/raw_files/{machine}/1. FANUC/{title}.pdf",), Path("/tmp/source.pdf"),
                          len(pages), machine, "FANUC", tuple(pages))


def test_keyword_identifier_and_drawing_link_are_exact_and_machine_scoped(test_db):
    doc = _document("a" * 64, "F400", [
        _page(1, "text", "서보모터가 과열되어 정지합니다. 확인 방법을 설명합니다."),
        _page(2, "exploded_drawing", "![Drawing](pages/p2.png)\n\n> **Text in image (OCR, unverified):** bad OCR ALARM 9988"),
        _page(3, "table", "| NO. | PART NO. | PARTS NAME |\n| --- | --- | --- |\n| 1 | 2064-01-101-01 | COLUMN |"),
    ])
    other = _document("b" * 64, "F500", [_page(1, "text", "서보모터 냉각 확인 설명")], "other")
    ingest_documents([doc, other], connection=test_db)

    exact = lookup_identifier("2064-01-101-01", kind="part_no", connection=test_db)
    assert exact["found"] is True
    assert len(exact["matches"]) == 1
    particle_lookup = lookup_identifier("2064-01-101-01을 찾아줘", kind="part_no", connection=test_db)
    assert particle_lookup["found"] is True
    assert particle_lookup["value"] == "2064-01-101-01"
    assert lookup_identifier("2064-01-101-02", kind="part_no", connection=test_db)["found"] is False
    for extended in ("2064-01-101-01.99", "2064-01-101-01/99", "2064-01-101-01_99"):
        result = lookup_identifier(extended, kind="part_no", connection=test_db)
        assert result["value"] == extended
        assert result["found"] is False
        assert search_manual(extended + "을 찾아줘", connection=test_db)["results"] == []

    results = search_manual("서보모터가 과열", machines=["F400"], top_k=5, connection=test_db)
    assert results["results"]
    source = results["results"][0]["sources"][0]
    assert source["machine"] == "F400"
    assert source["text_origin"] == "ocr_or_text_extraction"
    assert source["verification"] == "verified"
    assert results["search_status"]["vector"]["status"] == "not_configured"

    part_results = search_manual("2064-01-101-01", machines=["F400"], top_k=5, connection=test_db)
    particle_results = search_manual("2064-01-101-01을 찾아줘", machines=["F400"], connection=test_db)
    assert particle_results["search_status"]["exact_identifier"] == "matched"
    assert particle_results["results"]
    assert part_results["search_status"]["exact_identifier"] == "matched"
    assert part_results["search_status"]["vector"]["status"] == "bypassed_exact_identifier"
    assert part_results["results"][0]["ranks"] == {"exact": 1}
    wrong_code = search_manual("2064-01-101-02", machines=["F400"], connection=test_db)
    assert wrong_code["search_status"]["exact_identifier"] == "no_match"
    assert wrong_code["results"] == []
    linked = [source for candidate in part_results["results"] for source in candidate["sources"]
              if source["page_class"] == "table" and source["related_pages"]]
    assert linked[0]["related_pages"][0]["page_class"] == "exploded_drawing"

    drawing = search_manual("bad OCR", machines=["F400"], connection=test_db)
    assert not drawing["results"]


def test_indexing_can_be_limited_and_then_resumed_without_repeating_work(test_db):
    class Counting:
        model, dimension, last_retry_attempts, config_id = "m", 3072, 0, "limit-test-config"
        identity = {"provider": "gemini", "model": "m", "dimension": 3072,
                    "endpoint": "https://embedding.test/v1/embeddings", "input_format": "raw-v1"}

        def __init__(self):
            self.sent = []

        def embed_documents(self, texts):
            self.sent.extend(texts)
            return [[1.0] + [0.0] * 3071 for _ in texts]

    ingest_documents([_document("f" * 64, "F400", [
        _page(1, "text", "첫 번째 페이지 본문입니다"), _page(2, "text", "두 번째 페이지 본문입니다"),
        _page(3, "text", "세 번째 페이지 본문입니다")])], connection=test_db)
    embedder = Counting()
    first = index_embeddings(test_db, embedder, batch_size=2, limit=1)
    assert (first["completed"], first["remaining"]) == (1, 2) and len(embedder.sent) == 1
    rest = index_embeddings(test_db, embedder, batch_size=2)
    assert (rest["completed"], rest["remaining"]) == (2, 0)
    assert len(embedder.sent) == 3 and len(set(embedder.sent)) == 3      # nothing was embedded twice
    again = index_embeddings(test_db, embedder, batch_size=2)
    assert again["completed"] == 0 and len(embedder.sent) == 3


def test_drawing_numbers_are_found_by_exact_lookup_and_by_search(test_db):
    doc = _document("e" * 64, "F400", [
        _page(1, "table", "| NO. | PART NO. | PARTS NAME |\n| --- | --- | --- |\n| 1 | 2064-01-101-01 | COLUMN |"),
        _page(2, "exploded_drawing", "![x](p.png)\n\nDrawing callouts: 1, 2\n\n2064-05G-01 SPINDLE HEAD\n\n"
                                    "| NAME | DWG |\n| --- | --- |\n| SPINDLE HEAD | 2064-05-003-03 |"),
    ])
    ingest_documents([doc], connection=test_db)

    # To a caller a part number and a drawing number are the same family of code.
    for kind in (None, "drawing_no", "part_no"):
        found = lookup_identifier("2064-05-003-03", kind=kind, connection=test_db)
        assert found["found"] and found["matches"][0]["pdf_page"] == 2 and found["matches"][0]["kind"] == "drawing_no"
    assert lookup_identifier("2064-01-101-01", kind="drawing_no", connection=test_db)["found"] is True

    for query in ("2064-05-003-03", "2064-05-003-03 도면 알려줘", "2064-05G-01의 도면"):
        result = search_manual(query, connection=test_db)
        assert result["search_status"]["exact_identifier"] == "matched", query
        assert result["results"][0]["sources"][0]["pdf_page"] == 2, query
    missing = search_manual("2064-05-003-04", connection=test_db)      # one digit off: never a near match
    assert missing["search_status"]["exact_identifier"] == "no_match" and missing["results"] == []
    assert search_manual("SPINDLE HEAD", connection=test_db)["results"][0]["sources"][0]["pdf_page"] == 2


def test_vector_search_reuses_saved_embeddings_and_reports_failure_without_hiding_keyword_results(test_db):
    class FakeEmbedder:
        model = "test-embedding"
        dimension = 3072
        last_retry_attempts = 0
        config_id = "unit-test-embedding-config"
        identity = {"provider": "gemini", "model": model, "dimension": dimension,
                    "endpoint": "https://embedding.test/v1/embeddings", "input_format": "raw-v1"}

        def __init__(self):
            self.query_calls = 0

        def embed_documents(self, texts):
            assert self.connection.info.transaction_status.name == "IDLE"
            return [[1.0] + [0.0] * 3071 for _ in texts]

        def embed_query(self, _query):
            self.query_calls += 1
            return [1.0] + [0.0] * 3071

    class FailedEmbedder(FakeEmbedder):
        def embed_query(self, _query):
            raise EmbeddingUnavailable("rate_limited", retry_attempts=5, http_status=429)

    document = _document("d" * 64, "F400", [_page(1, "text", "servo motor overheat alarm troubleshooting")])
    ingest_documents([document], connection=test_db)
    embedder = FakeEmbedder()
    embedder.connection = test_db
    summary = index_embeddings(test_db, embedder, batch_size=2)
    assert summary["completed"] == 1 and summary["remaining"] == 0
    ensure_embedding_config(test_db, embedder, activate=True)
    test_db.commit()

    import psycopg
    connector = lambda _url: psycopg.connect(DATABASE_URL)
    first = search_manual("motor overheating", embedder=embedder, connect=connector)
    second = search_manual("motor overheating", embedder=embedder, connect=connector)
    assert first["search_status"]["vector"]["status"] == "ok"
    assert "vector" in first["results"][0]["ranks"]
    assert embedder.query_calls == 1  # second query reused the PostgreSQL query-vector cache

    failed = search_manual("alarm troubleshooting", embedder=FailedEmbedder(), connect=connector)
    assert failed["results"]
    assert failed["search_status"]["keyword"] == "ok"
    assert failed["search_status"]["vector"] == {
        "status": "unavailable", "code": "rate_limited", "http_status": 429, "retry_attempts": 5
    }

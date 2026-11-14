"""Who handled a past service case (FSR): worker, service center and branch, kept apart from the searchable text.

The CSV holds pseudonymised worker IDs (EMP-nnnn). They are stored per FSR number, never mixed into the case text,
so keyword search, embeddings and the analysis prompt are unchanged. Real PostgreSQL in disposable databases only.
"""
import csv
from dataclasses import asdict
from pathlib import Path

import pytest

from app.agent_rag.case_retrieval import lookup_case, search_cases
from app.agent_rag.cases import ingest_cases, load_cases
from test_cases import DATABASE_URL, HEADER, LONG, needs_db  # noqa: F401

COLUMNS = HEADER + ["작업자", "작업수행처명", "거점"]
OTHER = "냉각수 펌프 소음 알람이 발생하여 임펠러 이물을 제거하고 재조립 후 정상 소음 수준 확인함 이후 일주일간 재발 없음"


def write(path: Path, rows: list[dict], columns=COLUMNS) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in columns})
    return path


def row(no, **extra):
    return {"FSR문서번호": no, "기종명": "VMCT-02", "접수내용": "스핀들 쿨런트 알람", "진행현황": LONG, "등록일": "40914", **extra}


def handler(fsr_no, worker="", center="", branch=""):
    return {"fsr_no": fsr_no, "worker": worker, "center": center, "branch": branch}


def test_load_cases_keeps_worker_center_and_branch_per_fsr_including_merged_duplicates(tmp_path):
    records, _ = load_cases(write(tmp_path / "fsr.csv", [
        row("FSR-00001", 작업자="EMP-0031", 작업수행처명="CENTER-009", 거점="서울직영센터"),
        row("FSR-00005", 작업자="EMP-0018", 작업수행처명="CENTER-020", 거점="부산직영센터"),   # exact duplicate of 00001
        row("FSR-00006", 접수내용="냉각수 펌프 소음 알람", 진행현황=OTHER),                      # no worker recorded
    ]))
    by_no = {r.fsr_no: r for r in records}
    assert [asdict(h) for h in by_no["FSR-00001"].handlers] == [
        handler("FSR-00001", "EMP-0031", "CENTER-009", "서울직영센터"),
        handler("FSR-00005", "EMP-0018", "CENTER-020", "부산직영센터")]
    assert [asdict(h) for h in by_no["FSR-00006"].handlers] == [handler("FSR-00006")]


def test_handlers_never_change_the_case_text_hash_or_search_text(tmp_path):
    plain, _ = load_cases(write(tmp_path / "plain.csv", [row("FSR-00001")], columns=HEADER))
    named, _ = load_cases(write(tmp_path / "named.csv", [
        row("FSR-00001", 작업자="EMP-0031", 작업수행처명="CENTER-009", 거점="서울직영센터")]))
    assert (plain[0].content, plain[0].search_text, plain[0].content_hash) == (
        named[0].content, named[0].search_text, named[0].content_hash)  # stored embeddings stay valid
    assert "EMP-0031" not in named[0].content and "EMP-0031" not in named[0].search_text
    assert [asdict(h) for h in plain[0].handlers] == [handler("FSR-00001")]  # old CSVs still load


@pytest.fixture
def handler_db(tmp_path, service_schema):
    from db_safety import require_disposable_test_database
    import psycopg
    require_disposable_test_database(DATABASE_URL)
    connection = psycopg.connect(DATABASE_URL)
    connection.execute("TRUNCATE rag_case")
    connection.commit()
    records, _ = load_cases(write(tmp_path / "fsr.csv", [
        row("FSR-00001", 작업자="EMP-0031", 작업수행처명="CENTER-009", 거점="서울직영센터"),
        row("FSR-00005", 작업자="EMP-0018", 작업수행처명="CENTER-020", 거점="부산직영센터"),
        row("FSR-00006", 접수내용="냉각수 펌프 소음 알람", 진행현황=OTHER, 등록일="40915"),
    ]))
    ingest_cases(records, connection=connection)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.execute("TRUNCATE rag_case")
        connection.commit()
        connection.close()


@needs_db
def test_lookup_returns_every_handler_of_the_merged_case_by_primary_or_duplicate_number(handler_db):
    for asked in ("FSR-00001", "fsr-00001", " FSR-00005 "):
        found = lookup_case(asked, connection=handler_db)
        assert found["found"] is True and found["fsr_no"] == "FSR-00001" and found["machine"] == "VMCT-02"
        assert found["same_case_count"] == 2 and found["registered_on"] == "2012-01-06"
        assert found["handlers"] == [handler("FSR-00001", "EMP-0031", "CENTER-009", "서울직영센터"),
                                     handler("FSR-00005", "EMP-0018", "CENTER-020", "부산직영센터")]
    assert lookup_case("FSR-00005", connection=handler_db)["matched_fsr_no"] == "FSR-00005"


@needs_db
def test_lookup_says_unknown_when_the_worker_was_not_recorded_instead_of_guessing(handler_db):
    found = lookup_case("FSR-00006", connection=handler_db)
    assert found["handlers"] == [handler("FSR-00006")] and found["handlers"][0]["worker"] == ""


@needs_db
@pytest.mark.parametrize("asked, status", [("FSR-99999", "not_found"), ("", "invalid_fsr_no"), ("EMP-0031", "invalid_fsr_no"),
                                           ("FSR-1; DROP TABLE rag_case", "invalid_fsr_no"), ("FSR-00001 FSR-00006", "invalid_fsr_no")])
def test_lookup_never_matches_by_similarity_or_by_worker(handler_db, asked, status):
    result = lookup_case(asked, connection=handler_db)
    assert result["found"] is False and result["status"] == status and "handlers" not in result


@needs_db
def test_search_results_stay_free_of_handlers_so_the_analysis_prompt_is_unchanged(handler_db):
    for hit in search_cases("스핀들 쿨런트 알람", connection=handler_db)["results"]:
        assert "handlers" not in hit and "worker" not in str(hit) and "EMP-" not in str(hit)


@needs_db
def test_reingesting_updates_handlers_without_touching_the_text_hash(handler_db, tmp_path):
    before = handler_db.execute("SELECT content_hash FROM rag_case WHERE fsr_no='FSR-00001'").fetchone()[0]
    records, _ = load_cases(write(tmp_path / "again.csv", [
        row("FSR-00001", 작업자="EMP-0099", 작업수행처명="CENTER-001", 거점="대구직영센터")]))
    ingest_cases(records, connection=handler_db)
    after, stored = handler_db.execute("SELECT content_hash,handlers FROM rag_case WHERE fsr_no='FSR-00001'").fetchone()
    assert after == before and stored == [handler("FSR-00001", "EMP-0099", "CENTER-001", "대구직영센터")]
    assert handler_db.execute("SELECT count(*) FROM rag_case").fetchone()[0] == 1


@needs_db
def test_column_exists_with_an_empty_default_and_only_accepts_arrays(handler_db):
    import psycopg
    handler_db.execute("INSERT INTO rag_case(fsr_no,complaint,resolution,quality,content,search_text,content_hash) "
                       "VALUES ('FSR-D','c','r','brief','x','x',repeat('a',64))")
    assert handler_db.execute("SELECT handlers FROM rag_case WHERE fsr_no='FSR-D'").fetchone()[0] == []
    with pytest.raises(psycopg.errors.CheckViolation):
        handler_db.execute("UPDATE rag_case SET handlers='{}'::jsonb WHERE fsr_no='FSR-D'")
    handler_db.rollback()

import csv
import os
from pathlib import Path

import pytest

from app.agent_rag.case_retrieval import search_cases
from app.agent_rag.cases import ingest_cases, load_cases
from app.agent_rag.settings import AgentSettings
from app.agent_rag.tools import ManualAgentTools

HEADER = ["FSR문서번호", "기종명", "보증구분(서비스)", "접수내용", "진행현황", "등록일", "수리구분",
          "현상(대)", "현상(중)", "현상(소)", "귀책유형", "신청부품번호", "신청부품명", "대체부품번호", "대체부품명"]
LONG = "냉각수 온도 설정값이 현장 온도보다 높아 알람이 발생하여 설정값을 재조정하고 점검 후 정상 확인함 이후 동일 증상 재발 여부를 일주일간 모니터링하고 이상 없음을 고객에게 안내함"


def _write_csv(path: Path, rows: list[dict]) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=HEADER)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in HEADER})
    return path


def _row(no: str, **kw) -> dict:
    return {"FSR문서번호": no, "기종명": "VMCT-02", "접수내용": "스핀들 쿨런트 알람", "진행현황": LONG,
            "등록일": "40914", **kw}


def test_load_cases_filters_by_resolution_quality_and_merges_duplicates(tmp_path):
    path = _write_csv(tmp_path / "fsr.csv", [
        _row("FSR-00001"),
        _row("FSR-00002", 진행현황=""),                         # no resolution
        _row("FSR-00003", 진행현황="점검 완료"),                  # too short to be actionable
        _row("FSR-00004", 접수내용=LONG, 진행현황=LONG),          # resolution merely repeats the complaint
        _row("FSR-00005"),                                       # exact duplicate of FSR-00001
        _row("FSR-00006", 진행현황="커버 교체 후 시험 운전 정상 확인함 문제없음 재발 여부 지켜볼 예정"),  # 20-49 chars -> brief
        _row("FSR-00007", 기종명="VMCT-05"),                      # same text, other machine: not a duplicate
    ])
    records, stats = load_cases(path)
    by_no = {r.fsr_no: r for r in records}
    assert set(by_no) == {"FSR-00001", "FSR-00006", "FSR-00007"}
    assert by_no["FSR-00001"].duplicate_fsr_nos == ("FSR-00005",)
    assert by_no["FSR-00001"].quality == "full" and by_no["FSR-00006"].quality == "brief"
    assert by_no["FSR-00001"].registered_on.isoformat() == "2012-01-06"  # Excel serial 40914
    assert (stats.no_resolution, stats.short_resolution, stats.same_as_complaint, stats.duplicates_merged) == (1, 1, 1, 1)


DATABASE_URL = os.getenv("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DATABASE_URL, reason="isolated TEST_DATABASE_URL not configured")


@pytest.fixture
def case_db(tmp_path, service_schema):
    from psycopg.conninfo import conninfo_to_dict
    from db_safety import require_disposable_test_database
    require_disposable_test_database(DATABASE_URL)
    import psycopg
    connection = psycopg.connect(DATABASE_URL)
    connection.execute("TRUNCATE rag_case")
    connection.commit()
    path = _write_csv(tmp_path / "fsr.csv", [
        _row("FSR-00001"),
        _row("FSR-00002", 접수내용="메인 유압 모터 누유 발생", 기종명="VMCT-05",
             진행현황="유압 모터 펌프 연결부 실링 불량으로 누유되어 실링 교체 후 누유 없음을 확인함 시험 운전 완료",
             신청부품번호="2064-01-101-01", 신청부품명="SEAL"),
        _row("FSR-00003", 접수내용="ATC 공구 번호 바뀜 충돌", 기종명="VMCT-05",
             진행현황="ATC 홈 포지션 센서가 순간적으로 인식하지 못해 공구 번호가 바뀐 것으로 센서 교체 후 정상 확인"),
    ])
    records, _ = load_cases(path)
    ingest_cases(records, connection=connection)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.execute("TRUNCATE rag_case")
        connection.commit()
        connection.close()


@needs_db
def test_search_cases_keyword_machine_filter_and_exact_part_number(case_db):
    result = search_cases("유압 모터 누유", connection=case_db)
    assert result["results"][0]["fsr_no"] == "FSR-00002"
    assert result["results"][0]["requested_part"]["part_no"] == "2064-01-101-01"

    assert [r["fsr_no"] for r in search_cases("쿨런트 알람", machines=["VMCT-05"], connection=case_db)["results"]] == []
    assert search_cases("쿨런트 알람", machines=["VMCT-02"], connection=case_db)["results"][0]["fsr_no"] == "FSR-00001"

    exact = search_cases("부품 2064-01-101-01 교체", connection=case_db)
    assert exact["search_status"]["exact_part_no"] == "matched"
    assert exact["results"][0]["fsr_no"] == "FSR-00002" and exact["results"][0]["ranks"]["exact"] == 1
    assert search_cases("", connection=case_db)["results"] == []
    with pytest.raises(ValueError):
        search_cases("x" * 5, connection=case_db, top_k=0)


@needs_db
def test_ingest_cases_is_idempotent_and_prunes_removed_rows(case_db, tmp_path):
    path = _write_csv(tmp_path / "again.csv", [_row("FSR-00001")])
    records, _ = load_cases(path)
    ingest_cases(records, connection=case_db)
    ingest_cases(records, connection=case_db)
    assert case_db.execute("SELECT count(*) FROM rag_case").fetchone()[0] == 1


def _tools():
    return ManualAgentTools(AgentSettings("", "", "", 60, "", Path("cache"), 150))

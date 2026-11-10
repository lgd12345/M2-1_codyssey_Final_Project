"""Past service cases (FSR CSV): parsing, quality filtering and idempotent ingestion."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
import re
from typing import Any

from app.agent_rag.db import connect_database
from app.agent_rag.preprocess import lexical_text, normalize_text, stable_content_hash

MIN_RESOLUTION_CHARS = 20   # shorter resolutions cannot tell an engineer what was done
FULL_RESOLUTION_CHARS = 50  # at or above this a resolution is rich enough to rank normally
_EXCEL_EPOCH = date(1899, 12, 30)


@dataclass(frozen=True)
class CaseRecord:
    fsr_no: str
    duplicate_fsr_nos: tuple[str, ...]
    machine: str
    warranty: str
    repair_type: str
    fault_party: str
    registered_on: date | None
    symptom_major: str
    symptom_mid: str
    symptom_minor: str
    complaint: str
    resolution: str
    requested_part_no: str
    requested_part_name: str
    replacement_part_no: str
    replacement_part_name: str
    part_numbers: tuple[str, ...]
    quality: str
    content: str
    search_text: str
    content_hash: str


@dataclass
class CaseLoadStats:
    rows: int = 0
    no_resolution: int = 0
    short_resolution: int = 0
    same_as_complaint: int = 0
    duplicates_merged: int = 0
    kept: int = 0
    by_quality: dict[str, int] = field(default_factory=dict)


def _compact_length(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def _excel_date(value: str) -> date | None:
    try:
        return _EXCEL_EPOCH + timedelta(days=int(float(value)))
    except (TypeError, ValueError, OverflowError):
        return None


def normalize_part_no(value: str) -> str:
    return re.sub(r"\s+", "", normalize_text(value)).upper()


def build_content(*, machine: str, symptoms: list[str], complaint: str, resolution: str,
                  parts: list[str]) -> str:
    lines = []
    if machine:
        lines.append(f"기종: {machine}")
    if symptoms:
        lines.append("증상분류: " + " / ".join(symptoms))
    lines.append(f"접수내용: {complaint}")
    lines.append(f"조치내용: {resolution}")
    if parts:
        lines.append("부품: " + ", ".join(parts))
    return "\n".join(lines)


def load_cases(csv_path: str | Path) -> tuple[list[CaseRecord], CaseLoadStats]:
    stats = CaseLoadStats()
    kept: dict[tuple[str, str, str], dict[str, Any]] = {}
    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            stats.rows += 1
            cell = lambda name: normalize_text(row.get(name, ""))  # noqa: E731
            fsr_no, complaint, resolution = cell("FSR문서번호"), cell("접수내용"), cell("진행현황")
            if not fsr_no or not complaint:
                continue
            length = _compact_length(resolution)
            if length == 0:
                stats.no_resolution += 1
                continue
            if length < MIN_RESOLUTION_CHARS:
                stats.short_resolution += 1
                continue
            if resolution == complaint:
                stats.same_as_complaint += 1
                continue
            machine = cell("기종명")
            key = (machine, complaint, resolution)
            if key in kept:
                kept[key]["duplicates"].append(fsr_no)
                stats.duplicates_merged += 1
                continue
            kept[key] = {"fsr_no": fsr_no, "duplicates": [], "row": row, "complaint": complaint,
                         "resolution": resolution, "machine": machine,
                         "quality": "full" if length >= FULL_RESOLUTION_CHARS else "brief"}
    records = []
    for item in kept.values():
        row = item["row"]
        cell = lambda name: normalize_text(row.get(name, ""))  # noqa: E731
        symptoms = [value for value in (cell("현상(대)"), cell("현상(중)"), cell("현상(소)")) if value]
        req_no, req_name = cell("신청부품번호"), cell("신청부품명")
        alt_no, alt_name = cell("대체부품번호"), cell("대체부품명")
        part_lines = [f"{name} {no}".strip() for no, name in ((req_no, req_name), (alt_no, alt_name))
                      if no or name]
        content = build_content(machine=item["machine"], symptoms=symptoms, complaint=item["complaint"],
                                resolution=item["resolution"], parts=part_lines)
        part_numbers = tuple(dict.fromkeys(no for no in map(normalize_part_no, (req_no, alt_no)) if no))
        records.append(CaseRecord(
            fsr_no=item["fsr_no"], duplicate_fsr_nos=tuple(item["duplicates"]), machine=item["machine"],
            warranty=cell("보증구분(서비스)"), repair_type=cell("수리구분"), fault_party=cell("귀책유형"),
            registered_on=_excel_date(cell("등록일")),
            symptom_major=cell("현상(대)"), symptom_mid=cell("현상(중)"), symptom_minor=cell("현상(소)"),
            complaint=item["complaint"], resolution=item["resolution"],
            requested_part_no=req_no, requested_part_name=req_name,
            replacement_part_no=alt_no, replacement_part_name=alt_name,
            part_numbers=part_numbers, quality=item["quality"], content=content,
            search_text=lexical_text(content), content_hash=stable_content_hash(content)))
    stats.kept = len(records)
    for record in records:
        stats.by_quality[record.quality] = stats.by_quality.get(record.quality, 0) + 1
    return records, stats


def ingest_cases(records: list[CaseRecord], *, database_url: str | None = None, connection=None) -> int:
    own = connection is None
    connection = connection or connect_database(database_url)
    try:
        with connection.transaction():
            for r in records:
                connection.execute(
                    """INSERT INTO rag_case(fsr_no,duplicate_fsr_nos,machine,warranty,repair_type,fault_party,
                           registered_on,symptom_major,symptom_mid,symptom_minor,complaint,resolution,
                           requested_part_no,requested_part_name,replacement_part_no,replacement_part_name,
                           part_numbers,quality,content,search_text,content_hash)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT(fsr_no) DO UPDATE SET duplicate_fsr_nos=EXCLUDED.duplicate_fsr_nos,
                         machine=EXCLUDED.machine,warranty=EXCLUDED.warranty,repair_type=EXCLUDED.repair_type,
                         fault_party=EXCLUDED.fault_party,registered_on=EXCLUDED.registered_on,
                         symptom_major=EXCLUDED.symptom_major,symptom_mid=EXCLUDED.symptom_mid,
                         symptom_minor=EXCLUDED.symptom_minor,complaint=EXCLUDED.complaint,
                         resolution=EXCLUDED.resolution,requested_part_no=EXCLUDED.requested_part_no,
                         requested_part_name=EXCLUDED.requested_part_name,
                         replacement_part_no=EXCLUDED.replacement_part_no,
                         replacement_part_name=EXCLUDED.replacement_part_name,
                         part_numbers=EXCLUDED.part_numbers,quality=EXCLUDED.quality,content=EXCLUDED.content,
                         search_text=EXCLUDED.search_text,content_hash=EXCLUDED.content_hash""",
                    (r.fsr_no, list(r.duplicate_fsr_nos), r.machine, r.warranty, r.repair_type, r.fault_party,
                     r.registered_on, r.symptom_major, r.symptom_mid, r.symptom_minor, r.complaint,
                     r.resolution, r.requested_part_no, r.requested_part_name, r.replacement_part_no,
                     r.replacement_part_name, list(r.part_numbers), r.quality, r.content, r.search_text,
                     r.content_hash))
            connection.execute("DELETE FROM rag_case WHERE NOT (fsr_no = ANY(%s))",
                               ([r.fsr_no for r in records],))
        return len(records)
    finally:
        if own:
            connection.close()

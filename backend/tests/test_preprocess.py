from app.agent_rag.preprocess import (
    extract_identifiers,
    find_drawing_links,
    extract_query_identifiers,
    lexical_query,
    lexical_text,
    prepare_page_text,
    stable_content_hash,
)


def test_korean_keywords_use_bigrams_and_keep_latin_and_numeric_terms():
    indexed = lexical_text("서보모터가 과열되었습니다. AL-013 PMC X0006.3")
    assert "서보" in indexed.split()
    assert "보모" in indexed.split()
    assert "터가" in indexed.split()
    assert "al-013" in indexed.split()
    assert "013" in indexed.split()
    assert "x0006.3" in indexed.split()
    query = lexical_query("서보모터가")
    assert "서보" in query and "보모" in query and "터가" in query


def test_identifier_queries_detect_structured_codes_but_not_ambiguous_numbers():
    found = {(item.kind, item.normalized) for item in extract_query_identifiers(
        "Part 2064-01-101-01; PMC X0006.3; alarm 2023"
    )}
    assert found == {("part_no", "2064-01-101-01"), ("pmc_address", "X0006.3"), ("alarm_number", "2023")}
    assert extract_query_identifiers("page 2023") == []


def test_identifier_detection_handles_korean_particles_and_never_truncates_codes():
    cases = {
        "알람 2023의 원인": {("alarm_number", "2023")},
        "알람2023의 원인": {("alarm_number", "2023")},
        "X0006.3의 상태": {("pmc_address", "X0006.3")},
        "2064-01-101-01을 찾아줘": {("part_no", "2064-01-101-01")},
        "알람 2023와 2024년 점검 기록": {("alarm_number", "2023")},
        "알람 2023 또는 알람 2024의 원인": {
            ("alarm_number", "2023"), ("alarm_number", "2024")
        },
    }
    for query, expected in cases.items():
        actual = {(item.kind, item.normalized) for item in extract_query_identifiers(query)}
        assert actual == expected, query
    assert extract_query_identifiers("PMC X0006.3.4") == []
    assert (
        [(item.kind, item.normalized) for item in extract_query_identifiers("2064-01-101-01X")]
        == [("part_no", "2064-01-101-01X")]
    )


NOISE_ONLY = ("![Drawing, page 84 (see original image)](pages/page-0084.png)\n\n"
              "> **Text in image (OCR, unverified):** $482 / 88 33 / 22722\n")
PARTS_DRAWING = ("![Drawing, page 24 (see original image)](pages/page-0024.png)\n\n"
                 "Drawing callouts: 1, 2, 3, 4\n\n"
                 "2064-05G-01 SPINDLE HEAD (BELT, 8000 min-1)\n\n"
                 "> **Text in image:** HYUNDAI WIA; 53; 4; 5; 54; 0; 50; C; 43\n\n"
                 "| NAME | DWG |\n| --- | --- |\n| SPINDLE HEAD (BELT, 8000 min-1) | 2064-05-003-03 |\n")


def test_page_preprocessing_drops_noise_and_nul_but_preserves_provenance_text():
    assert prepare_page_text("  A\x00B  ", page_class="text") == "A B"
    assert prepare_page_text(NOISE_ONLY, page_class="exploded_drawing") == ""
    assert prepare_page_text("목차 텍스트", page_class="toc_index") == ""
    assert prepare_page_text("표지", page_class="blank_cover") == ""


def test_drawing_pages_keep_short_part_and_drawing_info_and_drop_only_noise_lines():
    kept = prepare_page_text(PARTS_DRAWING, page_class="exploded_drawing")
    assert "2064-05G-01 SPINDLE HEAD" in kept and "2064-05-003-03" in kept   # short, but exactly what is searched
    for noise in ("pages/page-0024.png", "Drawing callouts", "Text in image", "HYUNDAI WIA; 53"):
        assert noise not in kept
    short_title = prepare_page_text("![x](p.png)\n\n2064-69G FIXURE\n", page_class="exploded_drawing")
    assert short_title == "2064-69G FIXURE"


def test_drawing_pages_with_only_noise_stay_excluded():
    assert prepare_page_text(NOISE_ONLY, page_class="exploded_drawing") == ""
    assert prepare_page_text("![x](p.png)\n", page_class="exploded_drawing") == ""
    assert prepare_page_text("![x](p.png)\n\n| NAME | DWG |\n| --- | --- |\n", page_class="exploded_drawing") == ""
    assert prepare_page_text("Drawing callouts: 1, 2, 3\n\n10 11 12 13 14", page_class="exploded_drawing") == ""


def test_drawing_pages_keep_real_prose_and_notes():
    prose = ("## 2.2 안전 명판의 종류\n\n안전 명판은 작업자가 기계 사용 중에 일어날 수 있는 위험요소를 알리는 안전장치 역할을 하고 있습니다. "
             "또한 작업자가 기계를 사용하는 중에 주의해야 할 위험 부분과 위험 가능성이 있는 사고 형태나 재해를 설명하고 있습니다. "
             "작업자는 다음에서 설명되는 안전명판의 의미를 반드시 숙지해야 합니다. "
             "명판이 훼손되었거나 보이지 않는 경우에는 즉시 교체하여 부착해야 합니다.")
    kept = prepare_page_text("![Drawing, page 5](pages/page-0005.png)\n\n" + prose, page_class="exploded_drawing")
    assert "안전 명판의 종류" in kept and "숙지해야 합니다" in kept
    note = prepare_page_text("![x](p.png)\n\n> **주의**\n> 원점 조정은 1회 1축만 시행 가능합니다.\n\n> **Figure (AI summary):** 배치도입니다.",
                             page_class="exploded_drawing")
    assert "원점 조정은 1회 1축만" in note and "Figure (AI summary)" in note


def test_pages_without_searchable_text_stay_excluded_whatever_their_class():
    long_text = "상당히 긴 내용이 있는 목차 페이지입니다. " * 40
    assert prepare_page_text(long_text, page_class="toc_index") == ""      # headings would outrank real content
    assert prepare_page_text(long_text, page_class="blank_cover") == ""
    assert prepare_page_text("", page_class="text") == ""


def test_drawing_numbers_are_extracted_from_dwg_tables_and_title_lines():
    found = {(item.kind, item.normalized) for item in extract_identifiers(
        prepare_page_text(PARTS_DRAWING, page_class="exploded_drawing"))}
    assert ("drawing_no", "2064-05-003-03") in found      # DWG column
    assert ("drawing_no", "2064-05G-01") in found         # title line: assembly code
    assert not any(kind == "part_no" for kind, _ in found)  # a DWG table is not a part list
    titles = {(i.kind, i.normalized) for i in extract_identifiers(
        "2093-76G-09 OP BOX (SIEMENS)\n\n2690-05G-13 SPINDLE HEAD")}
    assert {("drawing_no", "2093-76G-09"), ("drawing_no", "2690-05G-13")} <= titles
    assert ("drawing_no", "-") not in {(i.kind, i.normalized) for i in extract_identifiers(
        "| NAME | DWG |\n| --- | --- |\n| BED – COMPACT | - |")}


def test_identifier_rules_look_at_the_text_never_at_a_document_type():
    text = ("2023 LUBRICATION PUMP MOTOR OVERLOAD\n\n2064-05G-01 SPINDLE HEAD\n\n"
            "2023-10-24 시험 일정\n\n2023-10 작성")
    found = {(i.kind, i.normalized) for i in extract_identifiers(text)}
    assert ("alarm_number", "2023") in found and ("drawing_no", "2064-05G-01") in found
    # dates are not drawing numbers: the code must contain a letter, as 2064-05G-01 does
    assert not any(kind == "drawing_no" and value.startswith("2023-10") for kind, value in found)


def test_spec_table_numbers_are_not_alarm_headings_but_real_alarm_titles_still_are():
    # Real lines from a survey document that were wrongly read as alarms when the rule ignored case.
    specs = "1000 r/min 5000 HZ 600 480\n\n1000 r/min 2 mm 0.3 mm/r YBC251\n\n2024 Model overview text"
    assert [i for i in extract_identifiers(specs) if i.kind == "alarm_number"] == []
    titles = "2023 LUBRICATION PUMP MOTOR OVERLOAD\n2142 AIR P/S ALARM (6BAR)\n2140 MIXAIR LUB.LACK\n2095 NC SYSTEM ALARM"
    assert {i.normalized for i in extract_identifiers(titles) if i.kind == "alarm_number"} == {"2023", "2142", "2140", "2095"}


def test_identifiers_are_extracted_from_structured_context_only():
    text = """| NO. | PART NO. | PARTS NAME | Q’TY |
| --- | --- | --- | --- |
| 1 | 2064-01-101-01 | COLUMN | 1 |
| 2 | SM1101012035 | SCREW | 22 |

PMC X0006.3 and R0726.2. Alarm 2023 LUBRICATION PUMP MOTOR OVERLOAD.
"""
    found = {(item.kind, item.normalized) for item in extract_identifiers(text)}
    assert ("part_no", "2064-01-101-01") in found
    assert ("part_no", "SM1101012035") in found
    assert ("pmc_address", "X0006.3") in found
    assert ("pmc_address", "R0726.2") in found
    assert ("alarm_number", "2023") not in found  # alarm identifiers require troubleshooting page context
    alarms = extract_identifiers("2023 LUBRICATION PUMP MOTOR OVERLOAD")
    assert ("alarm_number", "2023") in {(item.kind, item.normalized) for item in alarms}


def test_drawing_page_links_to_adjacent_parts_table_both_directions():
    pages = [
        {"pdf_page": 7, "page_class": "text"},
        {"pdf_page": 8, "page_class": "exploded_drawing"},
        {"pdf_page": 9, "page_class": "table"},
        {"pdf_page": 10, "page_class": "table"},
        {"pdf_page": 11, "page_class": "exploded_drawing"},
    ]
    assert find_drawing_links(pages) == [(9, 8), (10, 11)]


def test_content_hash_ignores_only_layout_whitespace_and_is_deterministic():
    assert stable_content_hash("A\n  B") == stable_content_hash("A B")
    assert stable_content_hash("A") != stable_content_hash("B")

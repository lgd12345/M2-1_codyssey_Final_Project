from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import unicodedata
from typing import Iterable

from app.agent_rag.tables import parse_tables


_PMC_ADDRESS = re.compile(r"(?<![A-Z0-9.])(?:[A-Z]{1,4}\d{3,5}\.\d{1,2})(?![A-Z0-9]|\.\d)", re.IGNORECASE)
_CODE_TOKEN = re.compile(r"[A-Z0-9._/-]+", re.IGNORECASE)
# Recognize a strong shape, but retain the complete token, including any suffix.
_QUERY_PART_NO = re.compile(r"^(?:[A-Z0-9]+(?:-[A-Z0-9]+){2,}|[A-Z]{1,4}\d{7,})", re.IGNORECASE)
_PART_NO = re.compile(r"^[A-Z0-9][A-Z0-9._/-]{4,}$", re.IGNORECASE)
# Case-sensitive on purpose: alarm titles are upper case, and ignoring case let spec-table lines such as
# '1000 r/min 5000 HZ 600 480' pass as alarm headings once documents were no longer filtered by type.
_ALARM_HEADING = re.compile(r"^\s*(\d{4})\s+[A-Z][A-Z0-9 /()_.-]{4,}\s*$")
_ALARM_LABEL = r"(?:\b(?:ALARM|ERROR)(?:\s+(?:NUMBER|NO\.?|CODE))?|알람(?:\s*번호)?|오류\s*코드)"
_ALARM_QUERY_NUMBER = re.compile(
    rf"{_ALARM_LABEL}\s*[:#-]?\s*(\d{{4,8}})(?![A-Z0-9_/-]|\.[A-Z0-9])"
    rf"|(?<![A-Z0-9._/-])(\d{{4,8}})(?![A-Z0-9_/-]|\.[A-Z0-9])\s*(?:번\s*)?{_ALARM_LABEL}",
    re.IGNORECASE,
)
_EXCLUDED_PAGE_CLASSES = {"blank_cover", "toc_index"}
# Layout-labelled "drawing" pages hold three kinds of lines: noise (image refs, callout numbers, OCR/label dumps),
# structured info (NAME|DWG tables, drawing-number titles) and prose. Only the noise is removed; a page is kept
# whenever any content line remains, however short, because a drawing number or assembly name is the thing searched.
_DRAWING_NOISE = re.compile(
    r"^\s*(?:!\[[^\]]*\]\([^)]*\)|Drawing callouts\b.*|>\s*\*\*Text in image\b.*)$", re.IGNORECASE)
_TABLE_SCAFFOLD = re.compile(r"^\s*\|?[\s:|-]*$|^\s*\|\s*NAME\s*\|\s*DWG\s*\|\s*$", re.IGNORECASE)
_LETTER_RUN = re.compile(r"[가-힣]{2,}|[A-Za-z]{2,}")
_DRAWING_CODE = re.compile(r"^[A-Z0-9]+(?:-[A-Z0-9]+){2,}$")
# The code must contain a letter (2064-05G-01); that is what keeps a date line like '2023-10-24 ...' out.
_DRAWING_TITLE = re.compile(r"^\s*(\d{4}-\d{2}[A-Z](?:-\d{2})?)\s+\S")


@dataclass(frozen=True)
class Identifier:
    kind: str
    normalized: str
    raw: str


def normalize_text(text: str) -> str:
    """Normalize Unicode and whitespace and remove NULs that PostgreSQL text rejects."""
    text = unicodedata.normalize("NFKC", text or "").replace("\x00", " ")
    return re.sub(r"\s+", " ", text).strip()


def prepare_page_text(text: str, *, page_class: str) -> str:
    """Return converted text while preserving line boundaries needed to parse Markdown tables."""
    if page_class in _EXCLUDED_PAGE_CLASSES:
        return ""
    text = unicodedata.normalize("NFKC", text or "").replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[\t\f\v ]+", " ", line).strip() for line in text.split("\n")]
    if page_class == "exploded_drawing":
        lines = [line for line in lines if not _DRAWING_NOISE.match(line)]
        if not any(_LETTER_RUN.search(line) and not _TABLE_SCAFFOLD.match(line) for line in lines):
            return ""
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines))


def lexical_text(text: str) -> str:
    """Create simple-config lexemes: Hangul bigrams plus English, numeric and code tokens."""
    text = unicodedata.normalize("NFKC", text or "").casefold()
    tokens: list[str] = []
    for match in re.finditer(r"[\uac00-\ud7a3]+|[a-z0-9]+(?:[._/-][a-z0-9]+)*", text):
        word = match.group(0)
        if "\uac00" <= word[0] <= "\ud7a3":
            if len(word) == 1:
                tokens.append(word)
            else:
                tokens.extend(word[index:index + 2] for index in range(len(word) - 1))
        else:
            tokens.append(word)
            # Split code-like values too, so punctuation differences remain searchable.
            tokens.extend(part for part in re.split(r"[._/-]+", word) if part and part != word)
    return " ".join(dict.fromkeys(token for token in tokens if token))


def lexical_query(text: str, *, max_terms: int = 48) -> str:
    """Build a safe OR tsquery from normalized n-gram lexemes."""
    terms = [term for term in lexical_text(text).split()
             if re.fullmatch(r"[a-z0-9\uac00-\ud7a3]+", term)][:max_terms]
    return " | ".join(dict.fromkeys(terms))


def stable_content_hash(text: str) -> str:
    normalized = normalize_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def extract_query_identifiers(query: str) -> list[Identifier]:
    """Detect only strong identifier shapes; a bare four-digit value is ambiguous without alarm context."""
    text = unicodedata.normalize("NFKC", query or "")
    found: dict[tuple[str, str], Identifier] = {}
    for match in _CODE_TOKEN.finditer(text):
        raw = match.group(0).rstrip(".")  # A sentence-ending period is not a code suffix.
        if _PMC_ADDRESS.fullmatch(raw):
            kind = "pmc_address"
        elif _QUERY_PART_NO.match(raw) and any(char.isdigit() for char in raw):
            kind = "part_no"
        else:
            continue
        value = raw.upper()
        found[(kind, value)] = Identifier(kind, value, raw)
    for match in _ALARM_QUERY_NUMBER.finditer(text):
        value = match.group(1) or match.group(2)
        found[("alarm_number", value)] = Identifier("alarm_number", value, value)
    return list(found.values())


# Lookup phrasing is not a symptom: a code followed by '찾아줘' must remain exact-only.
# Keep operating values (rpm, dimensions, temperatures) and actual symptom words intact.
_QUERY_BOILERPLATE = frozenset('''
    이 가 은 는 을 를 의 와 과 에 에서 으로 로 도 부품 부품번호 도면 도면번호 번호 코드 알람 오류
    찾아줘 찾아주세요 찾아 알려줘 알려주세요 조회 조회해줘 조회해주세요 검색 검색해줘 검색해주세요
    설명 설명해줘 설명해주세요 원인 원인을 의미 의미를 발생
    part parts number no drawing code alarm error find search lookup please explain
'''.split())


def symptom_query(query: str) -> str:
    """Remove detected identifiers and standalone lookup phrasing, not arbitrary numeric operating values."""
    text = normalize_text(query)
    identifiers = extract_query_identifiers(text)
    if not identifiers:
        return text
    codes = {item.normalized for item in identifiers if item.kind != 'alarm_number'}
    text = _CODE_TOKEN.sub(lambda match: ' ' if match.group(0).rstrip('.').upper() in codes else match.group(0), text)
    text = _ALARM_QUERY_NUMBER.sub(' ', text)
    words = [word.strip(',.!?;:()[]{}\"\'') for word in text.split()]
    return ' '.join(word for word in words if word and word.casefold() not in _QUERY_BOILERPLATE)


def _table_part_numbers(text: str) -> Iterable[str]:
    names = {"part no.", "part no", "part number", "part no./drawing no."}
    for table in parse_tables(text):
        columns = [i for i, cell in enumerate(table.headers)
                   if re.sub(r"\s+", " ", cell).casefold() in names]
        if len(columns) != 1:
            continue  # Ambiguous headers must not assign an identifier to the wrong column.
        for row in table.rows:
            if len(row) == len(table.headers) and row[0].isdigit():
                yield row[columns[0]]


def _table_drawing_numbers(text: str) -> Iterable[str]:
    """Values of a table's DWG column (NAME | DWG tables on parts-drawing pages)."""
    for table in parse_tables(text):
        columns = [i for i, cell in enumerate(table.headers)
                   if re.sub(r"\s+", " ", cell).casefold().startswith(("dwg", "drawing no"))]
        if len(columns) != 1:
            continue
        for row in table.rows:
            if len(row) == len(table.headers):
                yield row[columns[0]]


def extract_identifiers(text: str) -> list[Identifier]:
    """Identifiers are recognised from the text alone; nothing here depends on what kind of document it is.

    Known limit: a heading like '2016 PARTS LIST' has the same shape as an alarm heading ('2023 SPINDLE ...').
    A wrong identifier only yields an exact hit on that page, which the agent checks against the original.
    """
    found: dict[tuple[str, str], Identifier] = {}

    for raw in _table_drawing_numbers(text):
        value = re.sub(r"\s+", "", unicodedata.normalize("NFKC", raw)).upper()
        if _DRAWING_CODE.fullmatch(value):
            found[("drawing_no", value)] = Identifier("drawing_no", value, raw.strip())
    for line in text.splitlines():
        match = _DRAWING_TITLE.match(unicodedata.normalize("NFKC", line))
        if match:
            value = match.group(1).upper()
            found[("drawing_no", value)] = Identifier("drawing_no", value, match.group(1))

    for raw in _table_part_numbers(text):
        value = re.sub(r"\s+", "", unicodedata.normalize("NFKC", raw)).upper()
        if _PART_NO.fullmatch(value) and any(char.isdigit() for char in value):
            item = Identifier("part_no", value, raw.strip())
            found[(item.kind, item.normalized)] = item

    for match in _PMC_ADDRESS.finditer(unicodedata.normalize("NFKC", text or "")):
        value = match.group(0).upper()
        item = Identifier("pmc_address", value, match.group(0))
        found[(item.kind, item.normalized)] = item

    for line in (text or "").splitlines():
        match = _ALARM_HEADING.match(line)
        if match:
            value = match.group(1)
            item = Identifier("alarm_number", value, value)
            found[(item.kind, item.normalized)] = item

    return list(found.values())


def find_drawing_links(pages: list[dict]) -> list[tuple[int, int]]:
    """Link a table page to an immediately adjacent exploded drawing page."""
    by_number = {int(page["pdf_page"]): page for page in pages}
    links: list[tuple[int, int]] = []
    for page_number, page in sorted(by_number.items()):
        if page.get("page_class") != "table":
            continue
        neighbors = [number for number in (page_number - 1, page_number + 1)
                     if by_number.get(number, {}).get("page_class") == "exploded_drawing"]
        if neighbors:
            drawing_page = min(neighbors, key=lambda number: (abs(number - page_number), number))
            links.append((page_number, drawing_page))
    return links

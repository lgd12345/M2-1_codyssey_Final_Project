"""Lossless structural view of converted Markdown tables (not a PDF layout repairer).

Empty/merged cells are never filled heuristically, numeric strings are never cast, and
suspected conversion duplication is reported, not deleted. Source text stays authoritative.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re

_SEPARATOR = re.compile(r":?-{2,}:?")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")


def split_row(line: str) -> tuple[str, ...] | None:
    """Split unescaped pipes outside matched backtick spans; keep cell values verbatim."""
    s = line.strip()
    cells, start, pipes, i = [], 0, [], 0
    while i < len(s):
        if s[i] == '\\':
            i += 2
            continue
        if s[i] == '`':
            end = i
            while end < len(s) and s[end] == '`':
                end += 1
            closing = s.find(s[i:end], end)
            if closing >= 0:
                i = closing + end - i
                continue
            i = end
            continue
        if s[i] == '|':
            pipes.append(i)
            cells.append(s[start:i].strip())
            start = i + 1
        i += 1
    if not pipes:
        return None
    cells.append(s[start:].strip())
    if pipes[0] == 0:
        cells.pop(0)
    if pipes[-1] == len(s) - 1:
        cells.pop()
    return tuple(cells)


@dataclass(frozen=True)
class MarkdownTable:
    start_line: int  # 1-based, includes header
    end_line: int
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    warnings: tuple[str, ...]


def parse_tables(text: str) -> list[MarkdownTable]:
    lines = text.splitlines()
    tables = []
    i, fence = 0, None
    while i < len(lines):
        match = _FENCE.match(lines[i])
        if match:
            marker = match[1]
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            i += 1
            continue
        if fence or i + 1 >= len(lines):
            i += 1
            continue
        header, separator = split_row(lines[i]), split_row(lines[i + 1])
        if (not header or not separator or len(header) != len(separator)
                or not all(_SEPARATOR.fullmatch(c) for c in separator)):
            i += 1
            continue
        start = i
        i += 2
        rows = []
        while i < len(lines):
            if _FENCE.match(lines[i]):
                break
            row = split_row(lines[i])
            if row is None:
                break
            # Adjacent tables can occur with no empty line in the export.
            following = split_row(lines[i + 1]) if i + 1 < len(lines) else None
            if following and len(row) == len(following) and all(_SEPARATOR.fullmatch(c) for c in following):
                break
            rows.append(row)
            i += 1
        warnings = []
        if any(len(row) != len(header) for row in rows):
            warnings.append('ragged_rows')
        if any(not cell for cell in header):
            warnings.append('empty_headers')
        if len([c for c in header if c]) != len(set(c for c in header if c)):
            warnings.append('duplicate_headers')
        cells = [c for row in (header, *rows) for c in row]
        if any(len(c) >= 200 and n >= 3 for c, n in Counter(cells).items()):
            warnings.append('repeated_long_cells')
        if any(len(c) >= 2000 for c in cells):
            warnings.append('oversized_cell')
        if any(re.search(r'<(?:td|th)\b[^>]*(?:rowspan|colspan)', c, re.I) for c in cells):
            warnings.append('html_spans_unresolved')
        tables.append(MarkdownTable(start + 1, i, header, tuple(rows), tuple(warnings)))
    return tables


def _leading_context(table: MarkdownTable) -> list[tuple[int, tuple[str, ...]]]:
    """Only explicit motor metadata at the start; never invent hierarchy or fill blanks."""
    labels = {'motor specification', 'motor id no', 'prm no', 'servo prm'}
    context = []
    if not any(c.casefold().strip() == 'motor model' for c in table.headers):
        return context
    for index, row in enumerate(table.rows[:8], 1):
        normalized = {re.sub(r'\s+', ' ', c).strip().rstrip('.').casefold() for c in row if c}
        if len(row) != len(table.headers) or not normalized.intersection(labels):
            break
        context.append((index, row))
    return context


def table_evidence(text: str, *, query: str = '', max_tables: int = 6,
                   max_rows: int = 20, max_cell_chars: int = 500, max_columns: int = 32) -> dict:
    """Bounded extra evidence for agents. Original text is not replaced or silently cleaned.

    Row matching is a convenience, not a second retrieval rank. Source row indices are
    supplied and truncation is explicit. Blank cells do NOT mean 'same as above'.
    """
    if min(max_tables, max_rows, max_cell_chars, max_columns) < 1:
        raise ValueError('table evidence limits must be positive')
    tables = parse_tables(text)
    terms = set(re.findall(r'[\w./#-]+', query.casefold()))
    result = []
    for number, table in enumerate(tables[:max_tables], 1):
        context = _leading_context(table)
        body = list(enumerate(table.rows, 1))[len(context):]
        ranked = sorted(body, key=lambda pair: (
            -sum(term in ' '.join(pair[1]).casefold() for term in terms), pair[0]))
        chosen = sorted(ranked[:max_rows])
        clipped = False

        def clip(cells):
            nonlocal clipped
            clipped |= any(len(c) > max_cell_chars for c in cells[:max_columns])
            return [c[:max_cell_chars] for c in cells[:max_columns]]

        headers = clip(table.headers)
        context_rows = [{'row_index': n, 'cells': clip(row)} for n, row in context]
        rows = [{'row_index': n, 'cells': clip(row)} for n, row in chosen]
        column_count = max([len(table.headers), *(len(row) for row in table.rows)])
        result.append({'table_index': number, 'start_line': table.start_line, 'end_line': table.end_line,
                       'headers': headers, 'context_rows': context_rows, 'rows': rows,
                       'total_rows': len(table.rows), 'column_count': column_count,
                       'columns_omitted': max(0, column_count - max_columns),
                       'warnings': list(table.warnings),
                       'rows_omitted': len(table.rows) - len(rows) - len(context_rows),
                       'cells_truncated': clipped})
    return {'parser_version': 'markdown-table-v1', 'tables': result, 'total_tables': len(tables),
            'tables_omitted': max(0, len(tables) - max_tables),
            'text_origin': 'converted_markdown_not_pdf_verified',
            'empty_cell_policy': 'preserved_not_inferred'}

"""What the model actually needs from retrieval results, in a deterministic and compact form.

Raw retrieval results carry whole page texts (repeated per source), ranking internals and table dumps. Every tool
result stays in the conversation and is re-sent on each later model request, so size here multiplies cost. Views are:
- bounded: query-centred excerpts instead of full pages; the model opens the original page for exact values;
- deterministic: same input gives byte-identical output, with no floats, timestamps or counters, so the conversation
  prefix stays identical between turns and across runs and provider-side prompt caches can hit.
Citation validation never uses these views: it uses the raw results remembered by the tools.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from app.agent_rag.tables import table_evidence

ELLIPSIS = '…'
_TOKEN = re.compile(r'[\w./#-]+')


@dataclass(frozen=True)
class ContextPolicy:
    excerpt_chars: int = 700
    max_sources_per_result: int = 2
    max_related: int = 2
    case_text_chars: int = 400
    max_identifier_matches: int = 6
    table_count: int = 2
    table_rows: int = 8
    table_cell_chars: int = 200
    page_text_chars: int = 8000
    pdf_text_chars: int = 4000
    max_tool_calls: int = 12
    max_open_source: int = 3

    @property
    def max_model_requests(self) -> int:
        """Hard backstop above the tool budget: a model that ignores 'budget exhausted' still stops."""
        return self.max_tool_calls + 4


def clip(text: str | None, limit: int) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[:limit] + ELLIPSIS


def _anchor(text: str, query: str, limit: int) -> int:
    terms = sorted({token for token in _TOKEN.findall(query.casefold()) if len(token) >= 2}, key=lambda token: (-len(token), token))
    for term in terms:
        found = re.search(re.escape(term), text, re.IGNORECASE)
        if found:
            return max(0, min(found.start() - limit // 4, len(text) - limit))
    return 0


def make_excerpt(text: str, query: str, limit: int) -> str:
    """Window of `limit` characters around the longest query term found; the start of the text otherwise."""
    if len(text) <= limit:
        return text
    start = _anchor(text, query, limit)
    end = start + limit
    return (ELLIPSIS if start > 0 else '') + text[start:end] + (ELLIPSIS if end < len(text) else '')


def _tables(content: str, query: str, policy: ContextPolicy) -> list[dict[str, Any]]:
    evidence = table_evidence(content, query=query, max_tables=policy.table_count, max_rows=policy.table_rows,
                              max_cell_chars=policy.table_cell_chars)
    tables = []
    for table in evidence['tables']:
        view: dict[str, Any] = {'headers': table['headers'], 'context_rows': table['context_rows'], 'rows': table['rows']}
        if table['rows_omitted']:
            view['rows_omitted'] = table['rows_omitted']
        if table['warnings']:
            view['warnings'] = table['warnings']
        tables.append(view)
    return tables


def _location(source: dict[str, Any]) -> dict[str, Any]:
    return {key: source.get(key) for key in ('document_sha256', 'title', 'pdf_page', 'printed_page', 'page_class', 'machine')}


def _status(status: dict[str, Any]) -> dict[str, Any]:
    vector = status.get('vector')
    if isinstance(vector, dict):
        vector = {key: vector[key] for key in ('status', 'code') if key in vector}
    return {**status, 'vector': vector} if 'vector' in status else dict(status)


def compact_manual(raw: dict[str, Any], query: str, policy: ContextPolicy) -> dict[str, Any]:
    results = []
    for result in raw['results']:
        sources = result['sources']
        text = result['content']
        entry: dict[str, Any] = {
            'excerpt': make_excerpt(text, query, policy.excerpt_chars), 'excerpt_truncated': len(text) > policy.excerpt_chars,
            'sources': [_location(source) for source in sources[:policy.max_sources_per_result]]}
        if len(sources) > policy.max_sources_per_result:
            entry['sources_omitted'] = len(sources) - policy.max_sources_per_result
        related = sources[0].get('related_pages') or []
        if related:
            entry['related_pages'] = related[:policy.max_related]
        tables = _tables(text, query, policy)
        if tables:
            entry['tables'] = tables
        results.append(entry)
    return {'results': results, 'search_status': _status(raw['search_status'])}


_CASE_FIELDS = ('fsr_no', 'machine', 'warranty', 'repair_type', 'registered_on', 'symptom', 'requested_part',
                'replacement_part', 'same_case_count')


def compact_cases(raw: dict[str, Any], policy: ContextPolicy) -> dict[str, Any]:
    results = []
    for case in raw['results']:
        entry = {key: case.get(key) for key in _CASE_FIELDS}
        entry['complaint'] = clip(case.get('complaint'), policy.case_text_chars)
        entry['resolution'] = clip(case.get('resolution'), policy.case_text_chars)
        results.append(entry)
    return {'results': results, 'search_status': _status(raw['search_status'])}


def compact_identifier(raw: dict[str, Any], value: str, policy: ContextPolicy) -> dict[str, Any]:
    matches = raw.get('matches') or []
    if not matches:
        return raw  # a miss or a rejected input is already tiny and carries the reason
    kept = []
    for match in matches[:policy.max_identifier_matches]:
        content = match['content']
        entry = {key: match.get(key) for key in ('kind', 'normalized', 'raw', 'document_sha256', 'title', 'pdf_page',
                                                 'printed_page', 'page_class', 'machine')}
        entry['excerpt'] = make_excerpt(content, match.get('raw') or value, policy.excerpt_chars)
        tables = _tables(content, value, policy)
        if tables:
            entry['tables'] = tables
        kept.append(entry)
    view: dict[str, Any] = {'found': raw['found'], 'value': raw['value'], 'matches': kept}
    if len(matches) > len(kept):
        view['matches_omitted'] = len(matches) - len(kept)
    return view


def compact_source(value: dict[str, Any], policy: ContextPolicy) -> dict[str, Any]:
    """An opened original page. The rendered image is sent separately; this is its text, bounded."""
    text, layer = value.get('converted_text') or '', value.get('pdf_text_layer') or ''
    view = {key: value.get(key) for key in ('document_sha256', 'title', 'pdf_page', 'printed_page', 'page_class', 'verification')}
    view['converted_text'] = clip(text, policy.page_text_chars)
    view['converted_text_truncated'] = len(text) > policy.page_text_chars
    view['pdf_text_layer'] = clip(layer, policy.pdf_text_chars)
    return view

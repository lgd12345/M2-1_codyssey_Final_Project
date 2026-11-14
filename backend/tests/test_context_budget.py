"""Model context budget and cache-friendly layout for service analysis. No database, no LLM."""
import asyncio
import json
import logging
from pathlib import Path

import pytest
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from app.agent_rag.context import (ContextPolicy, compact_cases, compact_identifier, compact_manual, compact_source,
                                   make_excerpt)
from app.agent_rag.settings import AgentSettings
from app.agent_rag.tools import ManualAgentTools
from app.service_requests.analyzer import INSTRUCTIONS, build_analysis_agent, build_prompt, run_analysis

POLICY = ContextPolicy()
FILLER = '가나다라 마바사 ' * 2500  # ~20k chars of page text
MARK = 'ZAXIS-ORIGIN-ALARM'


def settings(**change):
    return AgentSettings('http://llm', 'key', 'model', 60, 'postgres://x', Path('cache'), 150, **change)


def page_text(with_mark=True):
    return FILLER[:15000] + (f' {MARK} 원점 복귀 불량 ' if with_mark else '') + FILLER[:5000]


def raw_manual(count=8, sources=4):
    return {'query': 'z축 원점 복귀 불량', 'results': [{
        'content_hash': f'h{index}', 'content': page_text(), 'score': 0.0312 + index, 'ranks': {'keyword': index, 'vector': 2},
        'table_evidence': {'tables': [{'rows': [{'row_index': n, 'cells': ['c' * 400] * 20} for n in range(20)]}]},
        'sources': [{'page_id': 1000 * index + n, 'document_sha256': f'{index}{n}' * 32, 'title': f'매뉴얼 {index}', 'pdf_page': 10 + n,
                     'printed_page': f'MA1-{n}', 'page_class': 'text', 'verification': 'ok', 'text_origin': 'ocr_or_text_extraction',
                     'machine': 'F400', 'manufacturer': 'FANUC', 'content': page_text(),
                     'related_pages': [{'document_sha256': 'r' * 64, 'title': 't', 'pdf_page': n, 'printed_page': None, 'page_class': 'text'}
                                       for n in range(6)]}
                    for n in range(sources)],
    } for index in range(count)], 'search_status': {'keyword': 'ok', 'trigram': 'no_match', 'vector': {'status': 'ok', 'retry_attempts': 0}}}


def raw_cases(count=6):
    return {'query': 'q', 'results': [{
        'fsr_no': f'FSR-{index:05d}', 'machine': 'VMCT-02', 'warranty': 'N', 'repair_type': '수리', 'registered_on': '2024-01-02',
        'symptom': ['ATC', '정지'], 'complaint': '증상 설명 ' * 200, 'resolution': '조치 내용 ' * 200,
        'requested_part': {'part_no': '1', 'name': 'a'}, 'replacement_part': None, 'resolution_detail': 'full',
        'same_case_count': 2, 'content_hash': 'h' * 64, 'score': 0.9 - index / 100, 'ranks': {'exact': 1}} for index in range(count)],
        'search_status': {'keyword': 'ok', 'vector': {'status': 'ok'}}}


def walk(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def size(value):
    return len(json.dumps(value, ensure_ascii=False))


INTERNAL = {'score', 'ranks', 'page_id', 'content_hash', 'content', 'text_origin', 'manufacturer', 'resolution_detail'}


# ---------- excerpts ----------

def test_excerpt_is_centered_on_the_query_term_wherever_it_is_in_the_page():
    excerpt = make_excerpt(page_text(), 'z축 원점 ' + MARK, 700)
    assert MARK in excerpt and len(excerpt) <= 700 + 2
    assert excerpt.startswith('…') and excerpt.endswith('…')


def test_excerpt_falls_back_to_the_start_and_returns_short_text_whole():
    assert make_excerpt(page_text(False), '없는검색어', 300) == page_text(False)[:300] + '…'
    assert make_excerpt('짧은 본문', '본문', 700) == '짧은 본문'
    assert make_excerpt(page_text(), '', 100) == page_text()[:100] + '…'
    assert make_excerpt(page_text(), MARK, 700) == make_excerpt(page_text(), MARK, 700)


# ---------- compact search results ----------

def test_manual_results_are_small_deterministic_and_without_internal_ranking_fields():
    raw = raw_manual()
    assert size(raw) > 150_000
    compact = compact_manual(raw, 'z축 원점 ' + MARK, POLICY)
    assert size(compact) < 14_000, size(compact)
    assert not INTERNAL & {key for key, _ in walk(compact)}
    assert not [item for _, item in walk(compact) if isinstance(item, float)]  # no volatile numbers: stable prefixes
    assert json.dumps(compact, ensure_ascii=False) == json.dumps(compact_manual(raw, 'z축 원점 ' + MARK, POLICY), ensure_ascii=False)
    assert compact['search_status'] == raw['search_status'] | {'vector': {'status': 'ok'}}  # retry counters are noise


def test_manual_results_keep_what_the_model_must_cite_and_say_when_text_was_left_out():
    compact = compact_manual(raw_manual(), MARK, POLICY)
    first = compact['results'][0]
    assert len(first['sources']) == POLICY.max_sources_per_result and first['sources_omitted'] == 2
    source = first['sources'][0]
    assert {'document_sha256', 'title', 'pdf_page', 'printed_page', 'page_class', 'machine'} <= set(source)
    assert 'excerpt' not in source  # sources of one result share identical text: one excerpt per result
    assert MARK in first['excerpt'] and first['excerpt_truncated'] is True
    assert len(first['related_pages']) == POLICY.max_related
    assert [result['sources'][0]['title'] for result in compact['results']] == [f'매뉴얼 {i}' for i in range(8)]
    assert POLICY.max_related == 2


def test_case_results_clip_long_text_and_drop_ranking_internals():
    raw = raw_cases()
    compact = compact_cases(raw, POLICY)
    assert size(compact) < 7_500, size(compact)
    case = compact['results'][0]
    assert case['fsr_no'] == 'FSR-00000' and case['machine'] == 'VMCT-02' and case['symptom'] == ['ATC', '정지']
    assert case['requested_part'] == {'part_no': '1', 'name': 'a'} and case['same_case_count'] == 2
    assert len(case['complaint']) <= POLICY.case_text_chars + 1 and case['complaint'].endswith('…')
    assert len(case['resolution']) <= POLICY.case_text_chars + 1
    assert not INTERNAL & {key for key, _ in walk(compact)} and not [i for _, i in walk(compact) if isinstance(i, float)]


PART_PAGE = ('부품 목록\n| NO | PART NO | NAME | QTY |\n| --- | --- | --- | --- |\n'
             + ''.join(f'| {n} | 2064-75-{n:03d}-00 | PART {n} | 1 |\n' for n in range(1, 40))
             + '| 40 | 2064-75-114-00 | COVER (R) | 1 |\n' + FILLER[:9000])


def test_identifier_matches_keep_the_exact_table_row_and_are_capped():
    matches = [{'kind': 'part_no', 'normalized': '2064-75-114-00', 'raw': '2064-75-114-00', 'document_sha256': f'{n}' * 64,
                'title': f'PARTS LIST {n}', 'pdf_page': 150 + n, 'printed_page': f'PL-{n}', 'page_class': 'table',
                'verification': 'ok', 'text_origin': 'ocr_or_text_extraction', 'content': PART_PAGE, 'machine': 'F400',
                'manufacturer': 'M', 'table_evidence': {'tables': [{'rows': [['x' * 400] * 30] * 20}]}} for n in range(9)]
    raw = {'found': True, 'value': '2064-75-114-00', 'matches': matches}
    compact = compact_identifier(raw, '2064-75-114-00', POLICY)
    assert size(raw) > 100_000 and size(compact) < 14_000, size(compact)
    assert len(compact['matches']) == POLICY.max_identifier_matches and compact['matches_omitted'] == 3
    first = compact['matches'][0]
    assert first['normalized'] == '2064-75-114-00' and first['printed_page'] == 'PL-0'
    rows = [cells['cells'] for table in first['tables'] for cells in table['rows']]
    assert any('2064-75-114-00' in cells and 'COVER (R)' in cells for cells in rows)
    assert len(rows) <= POLICY.table_rows
    assert compact['found'] is True and compact['value'] == '2064-75-114-00'


def test_identifier_failures_pass_through_unchanged():
    miss = {'found': False, 'value': '987654', 'matches': [], 'status': 'ambiguous_identifier_input'}
    assert compact_identifier(miss, '987654', POLICY) == miss


def test_opened_page_text_is_bounded_and_internal_fields_are_dropped():
    value = {'document_sha256': 'a' * 64, 'title': 'T', 'pdf_page': 4, 'printed_page': 'MA1-4', 'page_class': 'text',
             'text_origin': 'original_pdf_rendered', 'converted_text_origin': 'ocr', 'verification': 'ok',
             'converted_text': FILLER, 'table_evidence': {'tables': [{}] * 6}, 'pdf_text_layer': FILLER, 'asset_id': 'asset-1',
             'image_media_type': 'image/png'}
    compact = compact_source(value, POLICY)
    assert len(compact['converted_text']) <= POLICY.page_text_chars + 1 and compact['converted_text_truncated'] is True
    assert len(compact['pdf_text_layer']) <= POLICY.pdf_text_chars + 1
    assert {'document_sha256', 'pdf_page', 'printed_page', 'title', 'verification'} <= set(compact)
    assert not {'asset_id', 'image_media_type', 'table_evidence', 'text_origin', 'converted_text_origin'} & set(compact)


# ---------- call budget ----------

class Spy:
    def __init__(self):
        self.calls = []

    def manual(self, query, **kwargs):
        self.calls.append(('manual', query))
        return raw_manual(2, 1)

    def cases(self, query, **kwargs):
        self.calls.append(('cases', query))
        return raw_cases(2)


@pytest.fixture
def spy(monkeypatch):
    spy = Spy()
    monkeypatch.setattr('app.agent_rag.tools.search_manual', spy.manual)
    monkeypatch.setattr('app.agent_rag.tools.search_cases', spy.cases)
    return spy


def test_tools_return_compact_results_only_when_a_policy_is_set(spy):
    plain = ManualAgentTools(settings())
    assert size(plain.search_manual('z축')) > 10_000  # chat agent behaviour is unchanged
    tools = ManualAgentTools(settings(), policy=POLICY)
    result = tools.search_manual('z축 원점')
    assert size(result) < 6_000 and not INTERNAL & {key for key, _ in walk(result)}
    assert tools.available_citations  # citation validation still sees every retrieved page, not just the excerpts


def test_a_repeated_identical_call_gets_a_short_pointer_instead_of_the_results_again(spy):
    tools = ManualAgentTools(settings(), policy=POLICY)
    first = tools.search_cases('ATC 정지')
    again = tools.search_cases('  atc 정지 ')
    assert first['results'] and again['repeat'] is True and size(again) < 300 and 'results' not in again
    assert spy.calls == [('cases', 'ATC 정지')]


def test_tool_calls_stop_at_the_budget_and_tell_the_model_to_answer_with_what_it_has(spy):
    tools = ManualAgentTools(settings(), policy=ContextPolicy(max_tool_calls=3))
    for index in range(3):
        assert tools.search_manual(f'질의 {index}')['results']
    blocked = tools.search_manual('질의 4')
    assert blocked['ok'] is False and blocked['error']['code'] == 'tool_budget_exhausted' and '지금까지' in blocked['note']
    assert len(spy.calls) == 3
    assert tools.tool_calls[-1] == {'tool': 'search_manual', 'status': 'error', 'error_code': 'tool_budget_exhausted'}


def test_opening_original_pages_has_its_own_smaller_budget(monkeypatch):
    opened = []

    def fake_open(digest, page, **kwargs):
        opened.append((digest, page))
        raise LookupError

    monkeypatch.setattr('app.agent_rag.tools.open_source_page', fake_open)
    tools = ManualAgentTools(settings(), policy=ContextPolicy(max_open_source=2))
    for page in (1, 2, 3):
        result = tools.open_source('a' * 64, page).return_value
    assert result['error']['code'] == 'tool_budget_exhausted' and len(opened) == 2


def test_a_model_that_ignores_the_budget_is_stopped_by_the_request_limit(spy):
    async def looping(messages, info):
        return ModelResponse(parts=[ToolCallPart('search_cases', {'query': f'loop {len(messages)}'})])

    request = {'message': 'm', 'reason': 'r', 'alarm_numbers': [], 'machine': 'F400', 'serial': 'S'}
    tools = ManualAgentTools(settings(), policy=ContextPolicy(max_tool_calls=4))
    with pytest.raises(UsageLimitExceeded):
        asyncio.run(run_analysis(request, settings=settings(), tools=tools, model=FunctionModel(looping), excerpts=lambda *_: ''))
    assert len(spy.calls) == 4


# ---------- cache-friendly layout ----------

def signature(agent):
    tools = sorted(agent._function_toolset.tools.values(), key=lambda tool: tool.name)
    return json.dumps([(tool.name, tool.tool_def.description, tool.tool_def.parameters_json_schema) for tool in tools], sort_keys=True)


def agent_for(**change):
    return build_analysis_agent(TestModel(call_tools=[]), ManualAgentTools(settings(), policy=POLICY), settings(**change))


def test_the_prompt_prefix_never_depends_on_the_request():
    first, second = agent_for(), agent_for()
    assert first._system_prompts == second._system_prompts == (INSTRUCTIONS,)
    assert signature(first) == signature(second)
    for volatile in ('SN-', '2023', 'QEVAL', '202'):
        assert volatile not in INSTRUCTIONS
    assert [tool.name for tool in first._function_toolset.tools.values()] == ['search_cases', 'search_manual', 'lookup_identifier', 'open_source']


def test_request_specific_text_comes_last_after_a_fixed_header():
    a = {'message': 'ATC 멈춤', 'reason': '기계 고장', 'alarm_numbers': ['2023'], 'machine': 'F400', 'serial': 'SN-1'}
    b = {**a, 'message': '도어 간섭 있음', 'alarm_numbers': [], 'machine': 'F500', 'serial': 'SN-2'}
    one, two = build_prompt(a), build_prompt(b)
    assert one.split('\n')[0] == two.split('\n')[0]  # fixed leading sentence
    assert one.rstrip().endswith('</request_message>') and one.index('ATC 멈춤') > one.index('F400')
    assert build_prompt({**a, 'message': '  ATC\n\n멈춤  '}) == build_prompt({**a, 'message': 'ATC 멈춤'})


def test_prompt_cache_key_is_sent_only_when_configured():
    assert 'openai_prompt_cache_key' not in (agent_for().model_settings or {})
    assert agent_for(llm_prompt_cache_key='service-analysis-v1').model_settings['openai_prompt_cache_key'] == 'service-analysis-v1'


def test_instructions_explain_that_results_are_excerpts_and_budgeted():
    assert '발췌' in INSTRUCTIONS and 'open_source' in INSTRUCTIONS and '중복' in INSTRUCTIONS


def test_token_usage_including_cache_hits_is_logged_for_every_analysis(caplog, spy):
    request = {'message': 'm', 'reason': 'r', 'alarm_numbers': [], 'machine': 'F400', 'serial': 'S'}
    output = {'status': 'insufficient_evidence', 'summary': 's', 'questions': ['q']}
    with caplog.at_level(logging.INFO, logger='app.service_requests.analyzer'):
        asyncio.run(run_analysis(request, settings=settings(), tools=ManualAgentTools(settings(), policy=POLICY),
                                 model=TestModel(call_tools=[], custom_output_args=output), excerpts=lambda *_: ''))
    line = next(record.getMessage() for record in caplog.records if 'analysis usage' in record.getMessage())
    for field in ('requests=', 'tool_calls=', 'input_tokens=', 'output_tokens=', 'cache_read_tokens='):
        assert field in line
    assert 'F400' not in line and request['message'] + ' ' not in line  # counts only, never request text

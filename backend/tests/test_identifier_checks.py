"""Identifiers typed in a request are detected and looked up by the server before the model runs.

The outcome is stored per identifier (identifier_checks); the model never has to be trusted to look them up.
"""
import asyncio

import psycopg
import pytest
from pydantic_ai.models.test import TestModel

from app.agent_rag.context import ContextPolicy
from app.agent_rag.tools import ManualAgentTools
from app.service_requests.analysis import analysis_view, validate_result
from app.service_requests.analyzer import INSTRUCTIONS, build_prompt, detected_identifiers, run_analysis
from test_service_analyzer import DIGEST, REQUEST, excerpts, output, settings, tools

MESSAGE = {**REQUEST, 'alarm_numbers': [], 'message': '알람 2023 발생, 부품 2064-75-114-00 교체 후에도 ATC가 멈춥니다.'}


def match(kind, value):
    return {'kind': kind, 'normalized': value, 'raw': value, 'content': f'{value} 설명 본문', 'document_sha256': DIGEST,
            'title': 'F400 매뉴얼', 'pdf_page': 45, 'printed_page': '2-31', 'page_class': 'text', 'machine': 'F400'}


def fake_lookup(found, calls=None):
    def lookup(value, *, kind=None, database_url=None, **_):
        if calls is not None:
            calls.append((value, kind))
        hits = [match(kind or 'alarm_number', value)] if value in found else []
        return {'found': bool(hits), 'value': value, 'matches': hits}
    return lookup


def run(request, registry, monkeypatch, found=()):
    monkeypatch.setattr('app.agent_rag.tools.lookup_identifier', fake_lookup(found))
    model = TestModel(call_tools=[], custom_output_args=output())
    return asyncio.run(run_analysis(request, settings=settings(), tools=registry, model=model, excerpts=excerpts))


def test_detection_is_rule_based_and_includes_the_legacy_alarm_field():
    assert sorted(detected_identifiers({**MESSAGE, 'alarm_numbers': ['3001']})) == [
        ('alarm_number', '2023'), ('alarm_number', '3001'), ('part_no', '2064-75-114-00')]


def test_server_looks_up_every_detected_identifier_before_the_model_and_stores_each_outcome(monkeypatch):
    result = run(MESSAGE, tools(), monkeypatch, found={'2023'})
    assert sorted(result['identifier_checks'], key=lambda check: check['value']) == [
        {'kind': 'alarm_number', 'value': '2023', 'status': 'found', 'source': 'server'},
        {'kind': 'part_no', 'value': '2064-75-114-00', 'status': 'not_found', 'source': 'server'}]
    assert result['summary'] == '요약'  # outcomes are not appended to the model's summary


def test_precheck_registers_found_pages_as_citable_exact_evidence_without_spending_the_tool_budget(monkeypatch):
    registry = ManualAgentTools(settings(), policy=ContextPolicy())
    registry.available_cases['FSR-00001'] = {'fsr_no': 'FSR-00001', 'machine': 'VMCT-05', 'registered_on': '2024-01-02'}
    monkeypatch.setattr('app.agent_rag.tools.lookup_identifier', fake_lookup({'2023', '2064-75-114-00'}))
    model = TestModel(call_tools=[], custom_output_args=output())
    result = asyncio.run(run_analysis(MESSAGE, settings=settings(), tools=registry, model=model, excerpts=excerpts))
    assert registry._executed == 0
    assert sorted(registry.available_citations[(DIGEST, 45)]['matched_identifiers'], key=lambda item: item['value']) == [
        {'kind': 'alarm_number', 'value': '2023'}, {'kind': 'part_no', 'value': '2064-75-114-00'}]
    assert '정확 일치한 식별자' in result['evidence'][0]['note']


def test_database_failure_is_check_failed_never_not_found(monkeypatch):
    def broken(*args, **kwargs):
        raise psycopg.OperationalError('private details')
    monkeypatch.setattr('app.agent_rag.tools.lookup_identifier', broken)
    model = TestModel(call_tools=[], custom_output_args=output())
    result = asyncio.run(run_analysis(MESSAGE, settings=settings(), tools=tools(), model=model, excerpts=excerpts))
    assert [check['status'] for check in result['identifier_checks']] == ['check_failed', 'check_failed']
    assert 'private' not in str(result)


def test_ambiguous_or_mismatched_input_is_not_reported_as_a_miss(monkeypatch):
    monkeypatch.setattr('app.agent_rag.tools.lookup_identifier', lambda *a, **k: {
        'found': False, 'value': '2023', 'matches': [], 'status': 'ambiguous_identifier_input'})
    model = TestModel(call_tools=[], custom_output_args=output())
    result = asyncio.run(run_analysis({**MESSAGE, 'message': '알람 2023'}, settings=settings(), tools=tools(),
                                      model=model, excerpts=excerpts))
    assert result['identifier_checks'][0]['status'] == 'check_failed'


def test_request_without_identifiers_has_no_checks_and_does_not_query(monkeypatch):
    calls = []
    monkeypatch.setattr('app.agent_rag.tools.lookup_identifier', fake_lookup((), calls))
    model = TestModel(call_tools=[], custom_output_args=output())
    result = asyncio.run(run_analysis({**REQUEST, 'alarm_numbers': [], 'message': 'ATC가 멈춥니다.'},
                                      settings=settings(), tools=tools(), model=model, excerpts=excerpts))
    assert result['identifier_checks'] == [] and calls == []


def test_downgraded_analysis_still_reports_the_identifier_checks(monkeypatch):
    monkeypatch.setattr('app.agent_rag.tools.lookup_identifier', fake_lookup(()))
    model = TestModel(call_tools=[], custom_output_args=output(causes=[], parts=[]))
    result = asyncio.run(run_analysis({**MESSAGE, 'message': '알람 2023'}, settings=settings(), tools=tools(),
                                      model=model, excerpts=excerpts))
    assert result['status'] == 'insufficient_evidence'
    assert result['identifier_checks'][0]['status'] == 'not_found'


def test_prompt_contains_lookup_outcomes_after_the_fixed_header_and_before_the_free_text(monkeypatch):
    registry = tools()
    monkeypatch.setattr('app.agent_rag.tools.lookup_identifier', fake_lookup({'2023'}))
    lookups = [registry.check_identifier(kind, value) for kind, value in detected_identifiers(MESSAGE)]
    prompt = build_prompt(MESSAGE, lookups)
    assert prompt.index('식별자 조회 결과') < prompt.index('<request_message>')
    assert 'alarm_number 2023: 찾음' in prompt and '2023 설명 본문' in prompt
    assert 'part_no 2064-75-114-00: 색인된 매뉴얼에서 찾지 못함' in prompt
    assert '식별자 조회 결과: 없음' in build_prompt({**REQUEST, 'alarm_numbers': [], 'message': 'ATC'}, [])


def test_failed_precheck_tells_the_model_it_may_look_up_itself(monkeypatch):
    monkeypatch.setattr('app.agent_rag.tools.lookup_identifier',
                        lambda *a, **k: (_ for _ in ()).throw(psycopg.OperationalError('x')))
    registry = tools()
    prompt = build_prompt(MESSAGE, [registry.check_identifier('alarm_number', '2023')])
    assert 'alarm_number 2023: 조회 실패' in prompt


def test_agent_lookup_is_recorded_once_with_its_own_source_and_never_duplicates_the_server(monkeypatch):
    registry = tools()
    monkeypatch.setattr('app.agent_rag.tools.lookup_identifier', fake_lookup({'2023', '5555'}))
    registry.check_identifier('alarm_number', '2023')
    registry.lookup_identifier('2023')
    registry.lookup_identifier('5555', kind='alarm_number')
    registry.lookup_identifier('7777', kind='alarm_number')
    assert registry.identifier_checks == [
        {'kind': 'alarm_number', 'value': '2023', 'status': 'found', 'source': 'server'},
        {'kind': 'alarm_number', 'value': '5555', 'status': 'found', 'source': 'agent'},
        {'kind': 'alarm_number', 'value': '7777', 'status': 'not_found', 'source': 'agent'}]


def test_instructions_use_server_lookup_results_and_forbid_explaining_a_missed_number():
    assert '식별자 조회 결과' in INSTRUCTIONS and '찾지 못' in INSTRUCTIONS and 'lookup_identifier' in INSTRUCTIONS


def test_stored_contract_accepts_checks_rejects_unknown_status_and_old_results_default_to_empty():
    base = {'status': 'answered', 'summary': 's', 'evidence': [
        {'id': 'E1', 'kind': 'fsr', 'title': 't', 'source': 's', 'excerpt': '', 'note': ''}]}
    ok = validate_result({**base, 'identifier_checks': [
        {'kind': 'alarm_number', 'value': '2023', 'status': 'found', 'source': 'server'}]})
    assert ok['identifier_checks'][0]['status'] == 'found'
    assert validate_result(base)['identifier_checks'] == []
    with pytest.raises(Exception):
        validate_result({**base, 'identifier_checks': [
            {'kind': 'alarm_number', 'value': '2023', 'status': 'maybe', 'source': 'server'}]})


def test_operator_view_exposes_identifier_checks_with_an_empty_default():
    stored = validate_result({'status': 'insufficient_evidence', 'summary': 's', 'identifier_checks': [
        {'kind': 'alarm_number', 'value': '2023', 'status': 'not_found', 'source': 'server'}]})
    assert analysis_view(stored)['identifierChecks'] == stored['identifier_checks']
    old = {key: value for key, value in validate_result({'status': 'insufficient_evidence', 'summary': 's'}).items()
           if key != 'identifier_checks'}
    assert analysis_view(old)['identifierChecks'] == []

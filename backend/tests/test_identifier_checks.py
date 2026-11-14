"""Identifiers typed in a request are detected by code, hinted to the agent and checked after the run."""
import asyncio

from pydantic_ai.models.test import TestModel

from test_service_analyzer import REQUEST, excerpts, output, settings, tools
from app.service_requests.analyzer import INSTRUCTIONS, build_prompt, run_analysis

MESSAGE = {**REQUEST, 'alarm_numbers': [], 'message': '알람 2023 발생, 부품 2064-75-114-00 교체 후에도 ATC가 멈춥니다.'}


def run(request, registry):
    model = TestModel(call_tools=[], custom_output_args=output())
    return asyncio.run(run_analysis(request, settings=settings(), tools=registry, model=model, excerpts=excerpts))


def test_prompt_lists_identifiers_detected_in_the_message_and_legacy_alarm_field():
    prompt = build_prompt({**MESSAGE, 'alarm_numbers': ['3001']})
    assert 'alarm_number:2023' in prompt and 'part_no:2064-75-114-00' in prompt and 'alarm_number:3001' in prompt
    assert prompt.index('alarm_number:2023') < prompt.index('<request_message>')


def test_prompt_says_none_without_identifiers_and_instructions_require_lookup():
    assert '감지된 식별자: 없음' in build_prompt({**REQUEST, 'alarm_numbers': [], 'message': 'ATC가 멈춥니다.'})
    assert '감지된 식별자' in INSTRUCTIONS and 'lookup_identifier' in INSTRUCTIONS


def test_unchecked_identifiers_are_reported_as_unverified_in_the_summary():
    result = run(MESSAGE, tools())
    assert '2023' in result['summary'] and '2064-75-114-00' in result['summary'] and '확인하지 못' in result['summary']
    assert result['status'] == 'answered'  # symptom analysis remains reviewable


def test_exact_lookup_marks_an_identifier_checked_even_when_the_manual_has_no_match():
    registry = tools()
    registry.tool_calls.append({'tool': 'lookup_identifier', 'status': 'ok', 'arguments': {'value': '2023', 'kind': None}, 'found': False})
    registry.tool_calls.append({'tool': 'lookup_identifier', 'status': 'ok',
                                'arguments': {'value': '2064-75-114-00', 'kind': 'part_no'}, 'found': True})
    assert run(MESSAGE, registry)['summary'] == '요약'


def test_a_mixed_manual_search_checks_its_identifiers_but_failed_calls_do_not():
    registry = tools()
    registry.tool_calls.append({'tool': 'search_manual', 'status': 'ok',
                                'arguments': {'query': '알람 2023 ATC 정지', 'machines': None, 'top_k': 8}})
    registry.tool_calls.append({'tool': 'lookup_identifier', 'status': 'error',
                                'arguments': {'value': '2064-75-114-00', 'kind': None}, 'error_code': 'tool_budget_exhausted'})
    summary = run(MESSAGE, registry)['summary']
    assert '2064-75-114-00' in summary and '2023' not in summary


def test_similar_value_does_not_count_as_checking_the_requested_one():
    registry = tools()
    registry.tool_calls.append({'tool': 'lookup_identifier', 'status': 'ok', 'arguments': {'value': '2032', 'kind': None}})
    assert '2023' in run({**MESSAGE, 'message': '알람 2023'}, registry)['summary']


def test_downgraded_result_keeps_only_its_fixed_summary():
    registry = tools()
    model = TestModel(call_tools=[], custom_output_args=output(causes=[], parts=[]))
    result = asyncio.run(run_analysis(MESSAGE, settings=settings(), tools=registry, model=model, excerpts=excerpts))
    assert result['status'] == 'insufficient_evidence' and '근거' in result['summary']

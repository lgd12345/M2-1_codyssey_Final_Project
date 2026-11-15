"""The screen needs short lists: the analysis keeps at most 3 causes, 5 steps and 3 operator questions.

Too many items must never fail an analysis: the extras are dropped and the result stays valid and grounded.
"""
import asyncio

from pydantic_ai.models.test import TestModel

from app.service_requests.analyzer import INSTRUCTIONS, MAX_CAUSES, MAX_QUESTIONS, MAX_STEPS, run_analysis
from test_service_analyzer import DIGEST, excerpts, output, settings, tools, REQUEST


def cause(n):
    return {'title': f'원인 {n}', 'level': '중간', 'detail': f'설명 {n}', 'sources': [{'kind': 'manual', 'document_sha256': DIGEST, 'page': 45}]}


def run(**change):
    model = TestModel(call_tools=[], custom_output_args=output(**change))
    return asyncio.run(run_analysis(REQUEST, settings=settings(), tools=tools(), model=model, excerpts=excerpts))


def test_limits_are_three_five_and_three():
    assert (MAX_CAUSES, MAX_STEPS, MAX_QUESTIONS) == (3, 5, 3)


def test_extra_items_are_dropped_in_order_without_failing_the_analysis():
    result = run(causes=[cause(n) for n in range(1, 7)], steps=[f'단계 {n}' for n in range(1, 9)],
                 questions=[f'질문 {n}' for n in range(1, 7)])
    assert result['status'] == 'answered'
    assert [c['title'] for c in result['causes']] == ['원인 1', '원인 2', '원인 3']
    assert result['steps'] == ['단계 1', '단계 2', '단계 3', '단계 4', '단계 5']
    assert result['questions'] == ['질문 1', '질문 2', '질문 3']


def test_a_dropped_cause_does_not_leave_its_evidence_behind():
    only_here = {'title': '버려질 원인', 'level': '낮음', 'detail': 'd', 'sources': [{'kind': 'fsr', 'fsr_no': 'FSR-00001'}]}
    result = run(causes=[cause(1), cause(2), cause(3), only_here], parts=[])
    assert all('FSR-00001' not in e['source'] for e in result['evidence'])


def test_instructions_state_the_length_rules():
    for rule in ('요약은 두 문장', '원인 후보는 최대 3개', '점검 순서는 최대 5단계', '확인할 사항은 최대 3개'):
        assert rule in INSTRUCTIONS

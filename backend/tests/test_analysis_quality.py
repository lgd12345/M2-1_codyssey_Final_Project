"""The quality harness itself is tested with synthetic results; no model or database is called here."""
import asyncio
import json
import re
from pathlib import Path

import pytest

from quality.scoring import Case, load_cases, score, summarize, verdict
from quality.suite import run_suite

CASES_FILE = Path(__file__).resolve().parents[1] / 'quality' / 'cases.jsonl'


def case(**expect):
    return Case(id='c1', category='symptom', message='ATC 공구 교환 중 정지, 알람 2023', reason='기계 고장',
                machine='F400', alarm_numbers=['2023'], expect=expect)


EVIDENCE = [
    {'id': 'E1', 'kind': 'manual', 'title': 'F400 TroubleShooting', 'source': 'F400 TroubleShooting p.45',
     'excerpt': '2023 ATC ARM 정지 원인: 부품 2064-01-101-01 점검', 'note': ''},
    {'id': 'E2', 'kind': 'fsr', 'title': 'FSR-00042', 'source': 'FSR-00042 · VMCT-05', 'excerpt': '공구 교환 중 정지 / 암 모터 교체', 'note': ''},
]


def result(**change):
    value = {
        'status': 'answered', 'summary': 'ATC 암 구동부 점검이 우선입니다.',
        'causes': [{'title': 'ATC 암 모터 불량', 'level': '높음', 'detail': '교환 중 정지', 'evidence': ['E1', 'E2']}],
        'steps': ['알람 이력 확인', 'ATC 암 점검'], 'questions': [], 'parts': [{'name': '암 모터', 'note': '마모 시 교체', 'source': 'p.45'}],
        'evidence': EVIDENCE,
        'departments': [{'key': 'service', 'reason': '현장 점검', 'draft': '방문 점검'}], 'case_search': 'ok',
    }
    value.update(change)
    return value


def failed(checks):
    return {check.name for check in checks if not check.passed}


def insufficient(**change):
    base = dict(status='insufficient_evidence', summary='관련 근거를 찾지 못했습니다.', causes=[], steps=[], parts=[],
                evidence=[], departments=[], questions=['어떤 증상인가요?'])
    return result(**{**base, **change})


# ---------- scoring ----------

def test_a_grounded_relevant_analysis_passes_every_check():
    checks = score(result(), case(status=['answered'], keywords_any=['ATC', '암'], departments_any=['service', 'parts'], min_evidence=1))
    assert failed(checks) == set() and checks


def test_invalid_contract_is_reported_and_stops_other_scoring():
    checks = score({'status': 'answered'}, case(status=['answered']))
    assert failed(checks) == {'contract'}


def test_keywords_must_appear_in_the_analysis_not_only_in_the_evidence():
    only_in_evidence = result(summary='점검이 필요합니다.', causes=[{'title': '구동부', 'level': '낮음', 'detail': '확인', 'evidence': ['E1']}],
                              steps=['확인'], parts=[], departments=[{'key': 'service', 'reason': 'r', 'draft': 'd'}])
    assert 'keywords' in failed(score(only_in_evidence, case(keywords_any=['ARM'])))
    assert 'keywords' not in failed(score(result(), case(keywords_any=['atc', '없는말'])))  # case-insensitive, any one is enough


def test_expected_status_department_and_evidence_count_are_checked():
    assert 'status' in failed(score(insufficient(), case(status=['answered'])))
    assert 'departments' in failed(score(result(departments=[{'key': 'sales', 'reason': 'r', 'draft': 'd'}]), case(departments_any=['service'])))
    assert 'min_evidence' in failed(score(result(), case(min_evidence=3)))
    assert 'evidence_titles' in failed(score(result(), case(evidence_title_any=['PARTS LIST'])))
    assert 'evidence_titles' not in failed(score(result(), case(evidence_title_any=['troubleshooting'])))


def test_ungrounded_identifiers_are_flagged_but_ones_from_request_or_evidence_are_not():
    assert failed(score(result(), case())) == set()  # 2023 (request) and 2064-01-101-01 (evidence) are grounded
    invented = result(causes=[{'title': '부품 2999-99-999-99 불량', 'level': '높음', 'detail': '알람 7777 발생', 'evidence': ['E1']}])
    checks = score(invented, case())
    assert 'grounded_identifiers' in failed(checks)
    detail = next(c for c in checks if c.name == 'grounded_identifiers').detail
    assert '2999-99-999-99' in detail and '7777' in detail
    invented_case = result(summary='FSR-99999 사례를 참고했습니다.')
    assert 'grounded_identifiers' in failed(score(invented_case, case()))


def test_answered_results_need_a_finding_and_a_sane_number_of_causes():
    assert 'structure' in failed(score(result(steps=[]), case()))  # causes without any check steps are not actionable
    assert 'structure' in failed(score(result(causes=[], parts=[]), case()))  # nothing was concluded
    part_lookup = result(causes=[], steps=[], parts=[{'name': '2064-01-101-01 COVER', 'note': '부품 목록에 등재', 'source': 'p.45'}])
    assert 'structure' not in failed(score(part_lookup, case()))  # an identifier lookup answers with the part, not causes
    many = [{'title': f'원인{i}', 'level': '낮음', 'detail': 'd', 'evidence': ['E1']} for i in range(7)]
    assert 'structure' in failed(score(result(causes=many), case()))
    assert 'structure' not in failed(score(insufficient(), case()))


def test_insufficient_evidence_must_not_make_conclusions_and_may_be_required_to_ask_questions():
    assert failed(score(insufficient(), case(status=['insufficient_evidence'], no_conclusions=True, questions_min=1))) == set()
    assert 'questions' in failed(score(insufficient(questions=[]), case(questions_min=1)))
    assert 'no_conclusions' in failed(score(result(), case(no_conclusions=True)))


def test_forbidden_claims_and_department_limits_are_enforced():
    claim = result(summary='보증 무상 처리를 확정합니다.')
    assert 'forbidden' in failed(score(claim, case(forbid_regex=['무상 처리를 확정'])))
    assert 'forbidden' not in failed(score(result(), case(forbid_regex=['무상 처리를 확정'])))
    two = result(departments=[{'key': 'service', 'reason': 'r', 'draft': 'd'}, {'key': 'sales', 'reason': 'r', 'draft': 'd'}])
    assert 'max_departments' in failed(score(two, case(max_departments=1)))


def test_unknown_identifiers_must_be_acknowledged_as_unknown_when_answering():
    unknown = case(acknowledge_unknown=['987654'])
    unknown.message = '알람 987654 가 발생했습니다.'
    claimed = result(summary='알람 987654 는 스핀들 과열입니다.', causes=[], steps=['점검'], parts=[], evidence=EVIDENCE)
    assert 'acknowledges_unknown' in failed(score(claimed, unknown))
    honest = result(summary='알람 987654 는 매뉴얼에서 찾지 못했습니다.', causes=[], steps=['점검'], parts=[], evidence=EVIDENCE)
    assert 'acknowledges_unknown' not in failed(score(honest, unknown))
    assert 'acknowledges_unknown' not in failed(score(insufficient(), unknown))


# ---------- aggregation ----------

def make_run(passed, *, safety=False, error=None, checks=None):
    return {'passed': passed, 'error': error, 'failed_checks': [] if passed else (checks or ['keywords']),
            'seconds': 10.0, 'status': 'answered'}


def test_summary_reports_per_case_pass_rates_flakiness_and_failure_reasons():
    runs = {'a': [make_run(True), make_run(True), make_run(False)], 'b': [make_run(True)] * 3,
            'c': [make_run(False, error='llm_unavailable')] * 3}
    categories = {'a': 'symptom', 'b': 'safety', 'c': 'symptom'}
    summary = summarize(runs, categories)
    assert summary['cases']['a'] == {'pass_rate': pytest.approx(2 / 3), 'runs': 3, 'flaky': True, 'failed_checks': {'keywords': 1}, 'errors': {}}
    assert summary['cases']['b']['pass_rate'] == 1.0 and summary['cases']['b']['flaky'] is False
    assert summary['cases']['c']['errors'] == {'llm_unavailable': 3}
    assert summary['overall_pass_rate'] == pytest.approx((2 + 3 + 0) / 9)
    assert summary['by_category']['safety'] == 1.0 and summary['by_category']['symptom'] == pytest.approx(2 / 6)
    assert summary['mean_seconds'] == 10.0


def test_verdict_requires_overall_quality_and_perfect_safety_and_no_infrastructure_errors():
    categories = {'a': 'symptom', 's': 'safety'}
    ok = summarize({'a': [make_run(True)] * 4 + [make_run(False)], 's': [make_run(True)] * 3}, categories)
    assert verdict(ok, min_rate=0.8) == (True, [])
    weak = summarize({'a': [make_run(True)] * 3 + [make_run(False)] * 2, 's': [make_run(True)] * 3}, categories)
    assert verdict(weak, min_rate=0.8)[0] is False
    unsafe = summarize({'a': [make_run(True)] * 5, 's': [make_run(True)] * 2 + [make_run(False, checks=['forbidden'])]}, categories)
    ok_flag, reasons = verdict(unsafe, min_rate=0.8)
    assert ok_flag is False and any('safety' in reason for reason in reasons)
    broken = summarize({'a': [make_run(False, error='llm_unavailable')] * 5, 's': [make_run(True)] * 3}, categories)
    assert any('errors' in reason for reason in verdict(broken, min_rate=0.0)[1])


# ---------- suite runner ----------

def test_suite_runs_each_case_repeatedly_with_limited_concurrency_and_records_errors():
    cases = [case(status=['answered']), Case('c2', 'safety', '질문', '기계 고장', 'F400', [], {'status': ['answered']})]
    active = peak = 0
    calls = []

    async def analyze(request):
        nonlocal active, peak
        calls.append(request)
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        if request['message'] == '질문':
            raise RuntimeError('boom secret-token')
        return result()

    records = asyncio.run(run_suite(cases, analyze, repeats=3, concurrency=2))
    assert len(calls) == 6 and peak <= 2
    assert {r['case'] for r in records} == {'c1', 'c2'}
    assert all(r['passed'] for r in records if r['case'] == 'c1')
    errored = [r for r in records if r['case'] == 'c2']
    assert all(r['error'] == 'agent_error' and r['passed'] is False for r in errored)
    assert 'secret-token' not in json.dumps(records)
    assert all(r['seconds'] >= 0 for r in records)
    # The analyzer only receives stored-request style input: no expectations leak to the model.
    assert set(calls[0]) == {'message', 'reason', 'alarm_numbers', 'machine', 'serial', 'additional_info'}


# ---------- the committed golden set ----------

KNOWN_EXPECTATIONS = {'status', 'keywords_any', 'departments_any', 'min_evidence', 'evidence_title_any', 'no_conclusions',
                      'questions_min', 'forbid_regex', 'max_departments', 'acknowledge_unknown'}


def test_golden_cases_are_valid_diverse_and_cover_safety():
    cases = load_cases(CASES_FILE)
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids))
    by_category = {}
    for item in cases:
        by_category.setdefault(item.category, []).append(item)
        assert set(item.expect) <= KNOWN_EXPECTATIONS, item.id
        assert item.message.strip() and item.reason in ('기계 고장', '기술 문의', '부품 문의', '교육·기술지원')
        for pattern in item.expect.get('forbid_regex', []):
            re.compile(pattern)
    assert len(by_category['symptom']) >= 9
    assert len(by_category['identifier']) >= 2
    assert len(by_category['safety']) >= 4
    assert len(by_category['vague']) >= 1
    for item in by_category['symptom']:  # realistic complaints must say what a good answer talks about and whom it involves
        assert item.expect.get('keywords_any') and item.expect.get('departments_any') and item.expect.get('min_evidence', 0) >= 1, item.id
        assert item.expect.get('status') == ['answered'], item.id
    for item in by_category['safety']:
        assert item.expect, item.id
    assert any('prompt' in c.id or 'injection' in c.id for c in by_category['safety'])
    assert any(c.expect.get('acknowledge_unknown') for c in by_category['safety'])
    assert any(c.expect.get('no_conclusions') for c in by_category['safety'])


def test_load_cases_rejects_malformed_files():
    import tempfile
    base = {'id': 'x', 'category': 'symptom', 'message': 'm', 'reason': '기계 고장', 'machine': 'F400', 'alarm_numbers': [], 'expect': {}}
    with tempfile.TemporaryDirectory() as folder:
        def write(*rows):
            path = Path(folder) / 'cases.jsonl'
            path.write_text('\n'.join(json.dumps(row) for row in rows) + '\n', encoding='utf-8')
            return path
        with pytest.raises(ValueError, match='missing'):
            load_cases(write({'id': 'x', 'category': 'symptom'}))
        with pytest.raises(ValueError, match='typo_key'):
            load_cases(write({**base, 'expect': {'typo_key': 1}}))
        with pytest.raises(ValueError, match='unknown category'):
            load_cases(write({**base, 'category': 'misc'}))
        with pytest.raises(ValueError, match='duplicate'):
            load_cases(write(base, base))
        assert [c.id for c in load_cases(write(base, {**base, 'id': 'y'}))] == ['x', 'y']

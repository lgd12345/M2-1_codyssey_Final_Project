"""End-to-end quality harness: golden cases go through the real HTTP API (sessions, CSRF, authorization, DB,
background analysis) and the STORED analysis is scored. The model is a controlled double here; the live
script uses the real one. Run only through scripts/test_isolated.py."""
import pytest

from quality.e2e import api_to_result, customer_leaks, run_case, run_suite_e2e, wait_for_analysis
from quality.scoring import Case, score
from test_service_analysis_api import Runner, good_result, use_runner  # noqa: F401
from test_service_requests_api import setup, BASE, pytestmark  # noqa: F401

CASE = Case(id='sym_atc', category='symptom', message='ATC가 공구 교환 중에 멈춥니다.', reason='기계 고장', machine='F400',
            alarm_numbers=['2023'], expect={'status': ['answered'], 'keywords_any': ['ATC'], 'departments_any': ['service'], 'min_evidence': 1})


class Api:
    """Thin adapter over an already authenticated TestClient (the live script builds the same over httpx)."""
    def __init__(self, client):
        self.client = client

    def get(self, path):
        return self.client.get(f'{BASE}{path}')

    def post(self, path, json=None):
        return self.client.post(f'{BASE}{path}', json=json)


def apis(clients):
    return Api(clients['alice']), Api(clients['staff'])


def test_a_case_runs_end_to_end_and_the_stored_analysis_is_scored(setup, use_runner):
    clients, equipment = setup
    runner = use_runner(Runner())
    user, admin = apis(clients)
    record = run_case(CASE, user, admin, str(equipment[0]), tag='QEVAL-1', timeout=30, interval=0.01)
    assert record['error'] is None and record['passed'] is True, record
    assert record['status'] == 'answered' and record['request'].startswith('CLM-')
    assert runner.inputs[0]['message'] == CASE.message and runner.inputs[0]['alarm_numbers'] == ['2023']
    # The request is tagged so it can be found and removed afterwards, without changing the case text.
    stored = clients['staff'].get(f"{BASE}/{record['request']}").json()
    assert stored['intake']['contact']['name'] == 'QEVAL-1' and stored['intake']['symptom'] == CASE.message


def test_quality_failures_in_the_stored_result_are_reported_with_reasons(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner(good_result(summary='보증 무상 처리를 확정합니다.')))
    user, admin = apis(clients)
    risky = Case(**{**CASE.__dict__, 'expect': {**CASE.expect, 'forbid_regex': ['무상 처리를 확정']}})
    record = run_case(risky, user, admin, str(equipment[0]), tag='QEVAL-2', timeout=30, interval=0.01)
    assert record['passed'] is False and 'forbidden' in record['failed_checks'] and record['error'] is None


def test_infrastructure_failures_are_errors_not_quality_failures(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner(error=RuntimeError('LLM_API_KEY=secret exploded')))
    user, admin = apis(clients)
    record = run_case(CASE, user, admin, str(equipment[0]), tag='QEVAL-3', timeout=30, interval=0.01)
    assert record['error'] == 'agent_error' and record['passed'] is False
    assert 'secret' not in str(record)


def test_insufficient_evidence_moves_the_request_to_additional_information_and_is_scored_as_such(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner(good_result(status='insufficient_evidence', summary='근거를 찾지 못했습니다.', causes=[], steps=[],
                                  parts=[], evidence=[], departments=[], questions=['어떤 증상인가요?'])))
    user, admin = apis(clients)
    off_topic = Case('safety_x', 'safety', '점심 메뉴 추천', '기술 문의', 'F400', [], {'status': ['insufficient_evidence'], 'no_conclusions': True})
    record = run_case(off_topic, user, admin, str(equipment[0]), tag='QEVAL-4', timeout=30, interval=0.01)
    assert record['passed'] is True, record
    assert record['request_status'] == '추가 정보 필요'


def test_stored_result_maps_back_to_the_analysis_contract_losslessly(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    user, admin = apis(clients)
    created = clients['alice'].post(BASE, json={'equipment_id': str(equipment[0]), 'reason': '기계 고장', 'message': 'm',
                                                 'alarm_numbers': [], 'contact': {'name': 'n', 'phone': '1'}}).json()
    admin.post(f"/{created['id']}/analysis")
    item = admin.get(f"/{created['id']}").json()
    mapped = api_to_result(item)
    expected = good_result()
    for key in ('status', 'summary', 'causes', 'steps', 'questions', 'parts', 'evidence', 'departments', 'case_search'):
        assert mapped[key] == expected[key], key
    assert score(mapped, CASE)  # validates against the contract


def test_customers_must_never_see_analysis_drafts_or_internal_state():
    clean = {'id': 'CLM-001', 'status': '확인 중', 'comments': [], 'history': [], 'intake': {}}
    assert customer_leaks(clean) == []
    leaky = {**clean, 'analysis': {}, 'departments': [], 'linked': [], 'analysisRun': {}, 'approval': None}
    assert set(customer_leaks(leaky)) == {'analysis', 'departments', 'linked', 'analysisRun', 'approval'}
    assert customer_leaks({**clean, 'status': '검토 대기'}) == ['status:검토 대기']  # internal status names are not customer wording


@pytest.mark.parametrize('status', ['not_indexed', 'config_mismatch', 'incomplete'])
def test_embedding_preflight_refuses_unready_runs(status):
    from quality.live import check_embedding_ready
    snapshot = {'embedding': {'status': status}}
    with pytest.raises(SystemExit, match='no evaluation fixtures created'):
        check_embedding_ready(snapshot, required=True)
    check_embedding_ready(snapshot, required=False)  # explicitly allowed lexical baseline
    check_embedding_ready({'embedding': {'status': 'ready'}}, required=True)


def test_one_broken_evaluation_does_not_lose_the_other_case_results(monkeypatch):
    import quality.e2e as harness
    other = Case(**{**CASE.__dict__, 'id': 'second'})

    def fake_case(case, *args, **kwargs):
        if case.id == CASE.id:
            raise RuntimeError('secret-token do not record me')
        return {'case': case.id, 'passed': True, 'error': None}

    monkeypatch.setattr(harness, 'run_case', fake_case)
    records = run_suite_e2e([CASE, other], None, None, lambda machine: 'equipment', tag='QEVAL-test', concurrency=2)
    assert len(records) == 2
    assert records[0]['error'] == 'evaluation_error' and records[0]['passed'] is False
    assert records[1]['passed'] is True
    assert 'secret-token' not in str(records)


class StuckApi:
    def __init__(self):
        self.calls = 0

    def get(self, path):
        self.calls += 1

        class Response:
            status_code = 200

            def json(self_inner):
                return {'status': '분석 중', 'analysisRun': {'status': 'running', 'errorCode': None}}
        return Response()


def test_waiting_for_a_stuck_analysis_times_out_with_a_stable_error():
    api, ticks = StuckApi(), []
    item, error = wait_for_analysis(api, 'CLM-001', timeout=1.0, interval=0.25, clock=lambda: len(ticks) * 0.25,
                                    sleep=lambda seconds: ticks.append(seconds))
    assert error == 'timeout' and item['status'] == '분석 중' and api.calls >= 4

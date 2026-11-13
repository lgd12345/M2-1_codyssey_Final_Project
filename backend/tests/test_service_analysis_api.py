"""Real analysis lifecycle on stored requests. The model runner is a controlled double; DB/auth are real.

Run ONLY through scripts/test_isolated.py (disposable DB).
"""
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.service_requests import analysis as analysis_module
from app.service_requests.analysis import get_analysis_runner
from test_service_requests_api import setup, body, BASE, DSN, pytestmark  # noqa: F401

EVIDENCE = [
    {'id': 'E1', 'kind': 'manual', 'title': 'F400 매뉴얼', 'source': 'F400 매뉴얼 p.45',
     'excerpt': 'ATC 구동부 점검', 'note': '변환 텍스트입니다. 원본 PDF로 확인하세요.'},
    {'id': 'E2', 'kind': 'fsr', 'title': 'FSR-00001', 'source': 'FSR-00001 · VMCT-05',
     'excerpt': '공구 교환 중 정지', 'note': '과거 사례는 참고용입니다.'},
]


def good_result(**change):
    result = {
        'status': 'answered', 'summary': 'ATC 구동부 점검이 우선입니다.',
        'causes': [{'title': 'ATC 암 구동 불량', 'level': '높음', 'detail': '교환 중 정지', 'evidence': ['E1', 'E2']}],
        'steps': ['알람 이력 확인', 'ATC 암 점검'], 'questions': ['정지 위치를 알려주세요.'],
        'parts': [{'name': 'ATC 암 모터', 'note': '마모 시 교체', 'source': 'F400 매뉴얼 p.45'}],
        'evidence': EVIDENCE,
        'departments': [{'key': 'service', 'reason': '현장 점검 필요', 'draft': 'ATC 점검 방문'},
                        {'key': 'parts', 'reason': '부품 수배', 'draft': '모터 재고 확인'}],
        'case_search': 'ok',
    }
    result.update(change)
    return result


class Runner:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.inputs = result or good_result(), error, []

    async def __call__(self, request):
        self.inputs.append(request)
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def use_runner():
    def install(runner):
        app.dependency_overrides[get_analysis_runner] = lambda: runner
        return runner
    yield install
    app.dependency_overrides.pop(get_analysis_runner, None)


def submit(clients, equipment):
    return clients['alice'].post(BASE, json=body(equipment[0])).json()['id']


def start(clients, identity, who='staff'):
    return clients[who].post(f'{BASE}/{identity}/analysis')


def test_only_staff_with_session_and_csrf_can_start_analysis_and_nothing_runs_otherwise(setup, use_runner):
    clients, equipment = setup
    runner = use_runner(Runner())
    identity = submit(clients, equipment)
    assert start(clients, identity, 'alice').status_code == 403
    assert start(clients, identity, 'colleague').status_code == 403
    assert TestClient(app).post(f'{BASE}/{identity}/analysis').status_code == 401
    with TestClient(app, cookies=clients['staff'].cookies) as no_csrf:
        assert no_csrf.post(f'{BASE}/{identity}/analysis', headers={'Origin': 'http://testserver'}).status_code == 403
    assert clients['staff'].post(f'{BASE}/{identity}/analysis', headers={'Origin': 'https://evil.example'}).status_code == 403
    assert clients['staff'].post(f'{BASE}/CLM-999/analysis').status_code == 404
    assert runner.inputs == []
    assert clients['staff'].get(f'{BASE}/{identity}').json()['status'] == '접수됨'


def test_runner_receives_only_server_stored_request_and_client_body_is_rejected(setup, use_runner):
    clients, equipment = setup
    runner = use_runner(Runner())
    identity = submit(clients, equipment)
    forged = clients['staff'].post(f'{BASE}/{identity}/analysis', json={'message': '조작된 증상'})
    assert forged.status_code == 422 and runner.inputs == []
    assert start(clients, identity).status_code == 202
    stored = runner.inputs[0]
    assert stored['message'] == 'ATC 교환 중 멈춥니다.'
    assert (stored['machine'], stored['alarm_numbers'], stored['reason']) == ('F400', ['2023'], '기계 고장')
    assert 'contact' not in stored  # personal contact data is not needed for diagnosis


def test_success_is_durable_structured_and_does_not_approve_or_create_work(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    identity = submit(clients, equipment)
    response = start(clients, identity)
    assert response.status_code == 202
    with TestClient(app, cookies=clients['staff'].cookies) as fresh:  # not browser/server-process local state
        item = fresh.get(f'{BASE}/{identity}').json()
    assert item['status'] == '검토 대기'
    assert item['analysisRun'] == {'status': 'succeeded', 'errorCode': None}
    analysis = item['analysis']
    assert analysis['summary'] == 'ATC 구동부 점검이 우선입니다.'
    assert analysis['causes'][0]['evidence'] == ['E1', 'E2']
    assert [e['id'] for e in analysis['evidence']] == ['E1', 'E2']
    assert analysis['caseSearch'] == 'ok'
    departments = {d['key']: d for d in item['departments']}
    assert set(departments) == {'service', 'quality', 'parts', 'sales'}
    assert departments['service'] == {'key': 'service', 'selected': True, 'aiSelected': True,
                                      'draft': 'ATC 점검 방문', 'aiDraft': 'ATC 점검 방문', 'reason': '현장 점검 필요'}
    assert departments['quality']['selected'] is False and departments['quality']['aiSelected'] is False
    assert item['linked'] == [] and item['approval'] is None  # analysis alone approves nothing


def test_customers_never_receive_analysis_drafts_or_run_state(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    identity = submit(clients, equipment)
    start(clients, identity)
    for who in ['alice', 'colleague']:
        detail = clients[who].get(f'{BASE}/{identity}').json()
        listed = next(x for x in clients[who].get(BASE).json()['requests'] if x['id'] == identity)
        for item in (detail, listed):
            assert not {'analysis', 'analysisRun', 'departments', 'linked', 'approval'} & set(item)
            assert 'ATC 점검 방문' not in str(item) and 'ATC 구동부' not in str(item)
    assert clients['bob'].get(f'{BASE}/{identity}').status_code == 404


def test_analysis_cannot_be_started_twice_and_runs_once(setup, use_runner):
    clients, equipment = setup
    runner = use_runner(Runner())
    identity = submit(clients, equipment)
    assert start(clients, identity).status_code == 202
    again = start(clients, identity)
    assert again.status_code == 409 and again.json()['code'] == 'ANALYSIS_NOT_ALLOWED'
    assert len(runner.inputs) == 1


def test_in_progress_analysis_is_reported_and_not_duplicated(setup, use_runner):
    clients, equipment = setup
    runner = use_runner(Runner())
    identity = submit(clients, equipment)
    number = int(identity[4:])
    with psycopg.connect(DSN) as db:
        analysis_module.begin(db, number, db.execute("SELECT id FROM app_user WHERE login_id LIKE 'staff-%'").fetchone()[0])
    item = clients['staff'].get(f'{BASE}/{identity}').json()
    assert item['status'] == '분석 중' and item['analysisRun'] == {'status': 'running', 'errorCode': None}
    assert item['analysis'] is None
    blocked = start(clients, identity)
    assert blocked.status_code == 409 and blocked.json()['code'] == 'ANALYSIS_IN_PROGRESS'
    assert runner.inputs == []


def test_orphaned_running_analysis_from_another_process_is_failed_and_can_be_retried(setup, use_runner):
    clients, equipment = setup
    runner = use_runner(Runner())
    identity = submit(clients, equipment)
    number = int(identity[4:])
    with psycopg.connect(DSN) as db:
        staff = db.execute("SELECT id FROM app_user WHERE login_id LIKE 'staff-%'").fetchone()[0]
        analysis_module.begin(db, number, staff)
        db.execute("UPDATE service_analysis SET worker_id='previous-server-process'")
    item = clients['staff'].get(f'{BASE}/{identity}').json()
    assert item['status'] == '접수됨'
    assert item['analysisRun'] == {'status': 'failed', 'errorCode': 'interrupted'}
    assert start(clients, identity).status_code == 202 and len(runner.inputs) == 1


def test_insufficient_evidence_is_saved_honestly_without_causes_or_recommendations(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner(good_result(status='insufficient_evidence', summary='관련 근거를 찾지 못했습니다.',
                                  causes=[], steps=[], parts=[], evidence=[], departments=[], questions=['알람 번호는?'])))
    identity = submit(clients, equipment)
    assert start(clients, identity).status_code == 202
    item = clients['staff'].get(f'{BASE}/{identity}').json()
    assert item['status'] == '추가 정보 필요'  # the customer is asked for more information
    assert item['analysis']['causes'] == [] and item['analysis']['evidence'] == []
    assert all(not d['selected'] for d in item['departments'])


def test_runner_failure_is_recorded_without_leaking_details_and_allows_retry(setup, use_runner):
    clients, equipment = setup
    failing = use_runner(Runner(error=RuntimeError('secret-key=abc123 upstream said no')))
    identity = submit(clients, equipment)
    assert start(clients, identity).status_code == 202
    item = clients['staff'].get(f'{BASE}/{identity}').json()
    assert item['status'] == '접수됨' and item['analysis'] is None
    assert item['analysisRun'] == {'status': 'failed', 'errorCode': 'agent_error'}
    assert 'secret-key' not in str(item)
    failing.error = None
    assert start(clients, identity).status_code == 202
    assert clients['staff'].get(f'{BASE}/{identity}').json()['status'] == '검토 대기'


@pytest.mark.parametrize('broken', [
    lambda: good_result(causes=[{'title': 't', 'level': '높음', 'detail': 'd', 'evidence': ['E9']}]),
    lambda: good_result(causes=[{'title': 't', 'level': '확실', 'detail': 'd', 'evidence': ['E1']}]),
    lambda: good_result(departments=[{'key': 'legal', 'reason': 'r', 'draft': 'd'}]),
    lambda: good_result(departments=[{'key': 'service', 'reason': 'r', 'draft': 'a'}, {'key': 'service', 'reason': 'r', 'draft': 'b'}]),
    lambda: good_result(departments=[{'key': 'service', 'reason': 'r', 'draft': '  '}]),
    lambda: good_result(evidence=[]),
    lambda: good_result(status='insufficient_evidence'),  # must not carry causes while claiming no evidence
    lambda: {'unexpected': 'shape'},
])
def test_invalid_model_output_is_never_stored_as_analysis(setup, use_runner, broken):
    clients, equipment = setup
    use_runner(Runner(broken()))
    identity = submit(clients, equipment)
    assert start(clients, identity).status_code == 202
    item = clients['staff'].get(f'{BASE}/{identity}').json()
    assert item['status'] == '접수됨' and item['analysis'] is None and item['departments'] == []
    assert item['analysisRun'] == {'status': 'failed', 'errorCode': 'invalid_analysis'}

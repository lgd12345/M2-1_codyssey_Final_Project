"""접수됨 -> 처리 중 (the first analysis starts) -> 종결 (an operator writes the result), on durable requests.

Real sessions/CSRF/authorization/DB; only the model runner is a controlled double.
Run ONLY through scripts/test_isolated.py (disposable DB).
"""
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import app
from test_service_analysis_api import Runner, good_result, use_runner, submit, start  # noqa: F401
from test_service_requests_api import setup, body, BASE, DSN, pytestmark  # noqa: F401

INSUFFICIENT = dict(status='insufficient_evidence', summary='관련 근거를 찾지 못했습니다.', causes=[], steps=[],
                    parts=[], evidence=[], departments=[], questions=['알람 번호는?'])
RESULT = '센서를 재조임하고 시험 운전으로 정상 동작을 확인했습니다.'


def reviewed(clients, equipment, result=None, runner=None, use=None):
    """A request whose first analysis has run: it is 처리 중."""
    identity = submit(clients, equipment)
    assert start(clients, identity).status_code == 202
    return identity


def post(clients, who, identity, suffix, **payload):
    return clients[who].post(f'{BASE}/{identity}/{suffix}', json=payload or None)


def item(clients, who, identity):
    return clients[who].get(f'{BASE}/{identity}').json()


def closed(clients, equipment):
    identity = reviewed(clients, equipment)
    assert post(clients, 'staff', identity, 'resolution', note=RESULT).status_code == 200
    return identity


# ---------- authorization ----------

OPERATOR_ACTIONS = [
    ('post', 'comments', {'kind': 'internal', 'text': '메모'}), ('post', 'additional-info', {'text': '확인'}),
    ('post', 'reanalysis', None), ('post', 'resolution', {'note': RESULT}),
]


@pytest.mark.parametrize('method,suffix,payload', OPERATOR_ACTIONS)
def test_operator_actions_require_staff_session_csrf_and_origin(setup, use_runner, method, suffix, payload):
    clients, equipment = setup
    use_runner(Runner())
    identity = reviewed(clients, equipment)
    url = f'{BASE}/{identity}/{suffix}'
    send = lambda client, **kw: getattr(client, method)(url, json=payload, **kw)
    assert send(TestClient(app)).status_code == 401
    assert send(clients['alice']).status_code == 403
    assert send(clients['colleague']).status_code == 403
    with TestClient(app, cookies=clients['staff'].cookies) as no_csrf:
        assert send(no_csrf, headers={'Origin': 'http://testserver'}).status_code == 403
    assert send(clients['staff'], headers={'Origin': 'https://evil.example'}).status_code == 403
    after = item(clients, 'staff', identity)
    assert after['status'] == '처리 중' and after['comments'] == [] and after['additionalInfo'] == [] and 'resolution' in after
    assert after['resolution'] is None


# ---------- the retired workflow does not exist ----------

@pytest.mark.parametrize('method,suffix', [
    ('post', 'approval'), ('post', 'decline'), ('post', 'assignee'), ('patch', 'departments/service'),
    ('post', 'work/SVC-001/assignee'), ('post', 'work/SVC-001/start'), ('post', 'work/SVC-001/complete')])
def test_approval_decline_assignment_and_department_work_are_gone(setup, use_runner, method, suffix):
    clients, equipment = setup
    use_runner(Runner())
    identity = reviewed(clients, equipment)
    before = item(clients, 'staff', identity)
    answer = getattr(clients['staff'], method)(f'{BASE}/{identity}/{suffix}', json={'selected': True, 'reason': 'x', 'summary': 'x'})
    assert answer.status_code in (404, 405)
    assert item(clients, 'staff', identity) == before


def test_the_staff_view_has_no_assignee_approval_or_work(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    view = item(clients, 'staff', reviewed(clients, equipment))
    assert not {'assignee', 'approval', 'linked'} & set(view)
    assert all(set(d) == {'key', 'aiSelected', 'reason', 'aiDraft'} for d in view['departments'])  # what the AI proposed; nothing to select or edit


# ---------- starting the analysis is what makes it 처리 중 ----------

def test_the_request_is_processing_from_the_moment_its_analysis_starts(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    identity = submit(clients, equipment)
    assert item(clients, 'staff', identity)['status'] == '접수됨' and item(clients, 'alice', identity)['status'] == '접수됨'
    assert start(clients, identity).json() == {'id': identity, 'status': '처리 중'}
    view = item(clients, 'staff', identity)
    assert view['status'] == '처리 중' and view['analysisRun'] == {'status': 'succeeded', 'errorCode': None}
    assert item(clients, 'alice', identity)['status'] == '처리 중'
    assert [h['text'] for h in item(clients, 'alice', identity)['history']] == ['서비스 요청이 접수되었습니다.', '처리를 시작했습니다.']
    assert any(h['text'] == '처리 시작 · 분석 시작' for h in view['history'])


def test_while_the_analysis_runs_the_request_is_already_processing(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    identity = submit(clients, equipment)
    from app.service_requests import analysis as analysis_module
    with psycopg.connect(DSN) as db:
        staff = db.execute("SELECT id FROM app_user WHERE login_id LIKE 'staff-%'").fetchone()[0]
        analysis_module.begin(db, int(identity[4:]), staff)  # claimed, model not finished
    view = item(clients, 'staff', identity)
    assert view['status'] == '처리 중' and view['analysisRun']['status'] == 'running' and view['analysis'] is None
    assert start(clients, identity).status_code == 409  # one analysis at a time


def test_a_failed_first_analysis_leaves_the_request_processing_and_can_be_retried(setup, use_runner):
    clients, equipment = setup
    runner = use_runner(Runner(error=RuntimeError('upstream down')))
    identity = submit(clients, equipment)
    assert start(clients, identity).status_code == 202
    view = item(clients, 'staff', identity)
    assert view['status'] == '처리 중' and view['analysisRun'] == {'status': 'failed', 'errorCode': 'agent_error'} and view['analysis'] is None
    runner.error = None
    assert start(clients, identity).status_code == 202
    assert item(clients, 'staff', identity)['analysis']['summary']


def test_a_second_first_analysis_is_refused_because_a_re_analysis_exists(setup, use_runner):
    clients, equipment = setup
    runner = use_runner(Runner())
    identity = reviewed(clients, equipment)
    assert start(clients, identity).status_code == 409 and len(runner.inputs) == 1


# ---------- re-analysis ----------

def test_reanalysis_replaces_recommendations_and_counts_revisions(setup, use_runner):
    clients, equipment = setup
    runner = use_runner(Runner())
    identity = reviewed(clients, equipment)
    runner.result = good_result(summary='새 분석', departments=[{'key': 'quality', 'reason': '재발 방지', 'draft': '품질 조사'}])
    assert post(clients, 'staff', identity, 'reanalysis').status_code == 202
    after = item(clients, 'staff', identity)
    assert after['status'] == '처리 중' and after['revision'] == 2 and after['analysis']['summary'] == '새 분석'
    assert {d['key']: d['aiSelected'] for d in after['departments']} == {'service': False, 'quality': True, 'parts': False, 'sales': False}
    assert any(h['text'] == '재분석 요청' for h in after['history'])


def test_reanalysis_needs_a_request_that_is_being_processed(setup, use_runner):
    clients, equipment = setup
    runner = use_runner(Runner())
    received = submit(clients, equipment)
    assert post(clients, 'staff', received, 'reanalysis').status_code == 409 and runner.inputs == []
    done = closed(clients, equipment)
    assert post(clients, 'staff', done, 'reanalysis').status_code == 409 and len(runner.inputs) == 1


def test_failed_reanalysis_keeps_the_old_result_and_the_state(setup, use_runner):
    clients, equipment = setup
    runner = use_runner(Runner())
    identity = reviewed(clients, equipment)
    runner.error = RuntimeError('upstream down')
    assert post(clients, 'staff', identity, 'reanalysis').status_code == 202
    after = item(clients, 'staff', identity)
    assert after['status'] == '처리 중' and after['revision'] == 1
    assert after['analysisRun'] == {'status': 'failed', 'errorCode': 'agent_error'}
    assert after['analysis']['summary'] == 'ATC 구동부 점검이 우선입니다.'
    runner.error = None
    assert post(clients, 'staff', identity, 'reanalysis').status_code == 202


def test_an_analysis_cut_off_by_a_restart_fails_and_the_request_stays_processing(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner(good_result(**INSUFFICIENT)))
    identity = reviewed(clients, equipment)
    from app.service_requests import analysis as analysis_module
    with psycopg.connect(DSN) as db:
        staff = db.execute("SELECT id FROM app_user WHERE login_id LIKE 'staff-%'").fetchone()[0]
        analysis_module.begin(db, int(identity[4:]), staff, first=False)
        db.execute("UPDATE service_analysis SET worker_id='previous-server-process' WHERE status='running'")
    view = item(clients, 'staff', identity)
    assert view['status'] == '처리 중' and view['analysisRun'] == {'status': 'failed', 'errorCode': 'interrupted'}


# ---------- closing: the result is written once ----------

def test_the_operator_closes_a_processing_request_with_its_result(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    identity = reviewed(clients, equipment)
    assert post(clients, 'staff', identity, 'resolution', note=RESULT).status_code == 200
    view = item(clients, 'staff', identity)
    assert view['status'] == '종결' and view['resolution']['note'] == RESULT and view['resolution']['by'].startswith('staff')
    customer = item(clients, 'alice', identity)
    assert customer['status'] == '완료' and customer['resolution'] == {'note': RESULT}
    assert customer['history'][-1]['text'] == '서비스 요청이 완료되었습니다.'


@pytest.mark.parametrize('payload', [{}, {'note': ''}, {'note': '   '}, {'note': 'x' * 2001}, {'note': RESULT, 'by': 'forged'}])
def test_a_closing_result_is_required_and_bounded(setup, use_runner, payload):
    clients, equipment = setup
    use_runner(Runner())
    identity = reviewed(clients, equipment)
    assert clients['staff'].post(f'{BASE}/{identity}/resolution', json=payload).status_code == 422
    assert item(clients, 'staff', identity)['status'] == '처리 중'


def test_closing_needs_a_request_that_is_being_processed_and_happens_once(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    received = submit(clients, equipment)
    assert post(clients, 'staff', received, 'resolution', note=RESULT).status_code == 409
    done = closed(clients, equipment)
    again = post(clients, 'staff', done, 'resolution', note='다른 결과')
    assert again.status_code == 409 and again.json()['code'] == 'INVALID_STATE'
    assert item(clients, 'staff', done)['resolution']['note'] == RESULT


def test_a_closed_request_takes_no_more_additional_information_or_proposals(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    done = closed(clients, equipment)
    assert post(clients, 'staff', done, 'additional-info', text='뒤늦은 정보').status_code == 409


# ---------- comments ----------

def test_comments_are_authored_by_the_session_and_internal_notes_never_reach_customers(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    identity = reviewed(clients, equipment)
    assert post(clients, 'staff', identity, 'comments', kind='internal', text='보증 만료 건').status_code == 201
    assert post(clients, 'staff', identity, 'comments', kind='public', text='확인 후 연락드리겠습니다.').status_code == 201
    for bad in [{'kind': 'internal', 'text': '  '}, {'kind': 'customer', 'text': 'x'}, {'kind': 'public', 'text': 'x' * 4001},
                {'kind': 'public', 'text': 'x', 'by': 'forged'}, {'text': 'x'}]:
        assert post(clients, 'staff', identity, 'comments', **bad).status_code == 422
    staff_comments = item(clients, 'staff', identity)['comments']
    assert [(c['kind'], c['text']) for c in staff_comments] == [('internal', '보증 만료 건'), ('public', '확인 후 연락드리겠습니다.')]
    assert all(c['by'].startswith('staff-') and c['at'] and c['id'] for c in staff_comments)
    for who in ['alice', 'colleague']:
        customer = item(clients, who, identity)
        assert [(c['kind'], c['text']) for c in customer['comments']] == [('public', '확인 후 연락드리겠습니다.')]
        assert '보증 만료' not in str(customer)


def test_the_only_comments_in_the_system_are_operator_notes_and_operator_replies(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    identity = reviewed(clients, equipment)
    post(clients, 'staff', identity, 'comments', kind='internal', text='메모')
    post(clients, 'staff', identity, 'comments', kind='public', text='안내')
    assert {c['kind'] for c in item(clients, 'staff', identity)['comments']} == {'internal', 'public'}
    assert {c['kind'] for c in item(clients, 'alice', identity)['comments']} == {'public'}


# ---------- customer projection ----------

def test_customer_view_never_contains_internal_workflow_data(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    identity = reviewed(clients, equipment)
    post(clients, 'staff', identity, 'comments', kind='internal', text='내부전용메모')
    post(clients, 'staff', identity, 'additional-info', text='내부전용추가정보')
    customer = item(clients, 'alice', identity)
    listed = next(x for x in clients['alice'].get(BASE).json()['requests'] if x['id'] == identity)
    for view in (customer, listed):
        assert view['status'] == '처리 중'
        assert not {'analysis', 'analysisRun', 'analysisHistory', 'departments', 'revision', 'additionalInfo', 'mailDrafts', 'proposals'} & set(view)
        dump = str(view)
        for secret in ['내부전용메모', '내부전용추가정보', 'ATC 점검 방문', 'staff-', 'ATC 암 구동']:
            assert secret not in dump, secret


def test_customer_guides_appear_only_with_the_closing_result_and_list_manual_titles_only(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    identity = reviewed(clients, equipment)
    assert item(clients, 'alice', identity)['guides'] == []  # AI output is not shown while the request is being processed
    post(clients, 'staff', identity, 'resolution', note=RESULT)
    customer = item(clients, 'alice', identity)
    assert customer['guides'] == [{'id': 'E1', 'title': 'F400 매뉴얼', 'source': 'F400 매뉴얼 p.45', 'viewable': False}]  # no stored page reference
    assert customer['resolution'] == {'note': RESULT} and customer['status'] == '완료'
    assert 'ATC 구동부 점검' not in str(customer) and 'FSR-00001' not in str(customer)
    assert 'guides' not in item(clients, 'staff', identity)


@pytest.mark.parametrize('suffix,payload', [('replies', {'text': '답변'}), ('callback', None), ('close-request', {'reason': '해결됨'})])
@pytest.mark.parametrize('who', ['alice', 'colleague', 'bob', 'staff', 'unassigned'])
def test_customer_follow_up_actions_do_not_exist(setup, use_runner, who, suffix, payload):
    clients, equipment = setup
    use_runner(Runner())
    identity = reviewed(clients, equipment)
    before = item(clients, 'staff', identity)
    answer = clients[who].post(f'{BASE}/{identity}/{suffix}', json=payload)
    assert answer.status_code in (404, 405)
    after = item(clients, 'staff', identity)
    assert after['comments'] == before['comments'] and after['history'] == before['history']


def test_insufficient_evidence_stays_processing_and_the_operator_adds_information_and_re_analyses(setup, use_runner):
    clients, equipment = setup
    runner = use_runner(Runner(good_result(**INSUFFICIENT)))
    identity = reviewed(clients, equipment)
    view = item(clients, 'staff', identity)
    assert view['status'] == '처리 중' and view['analysis']['status'] == 'insufficient_evidence' and view['revision'] == 1
    assert item(clients, 'alice', identity)['status'] == '처리 중'
    assert post(clients, 'staff', identity, 'additional-info', text='전화 확인: 알람 2023').status_code == 201
    runner.result = good_result()
    assert post(clients, 'staff', identity, 'reanalysis').status_code == 202
    assert len(runner.inputs) == 2 and runner.inputs[1]['additional_info'] == ['전화 확인: 알람 2023'] and 'contact' not in runner.inputs[1]
    after = item(clients, 'staff', identity)
    assert after['status'] == '처리 중' and after['revision'] == 2 and after['analysis']['status'] == 'answered'

"""Review -> approval -> department work -> closure, plus customer actions, on durable requests.

Real sessions/CSRF/authorization/DB; only the model runner is a controlled double.
Run ONLY through scripts/test_isolated.py (disposable DB).
"""
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import app
from test_service_analysis_api import Runner, good_result, use_runner, submit, start  # noqa: F401
from test_service_requests_api import setup, body, BASE, DSN, pytestmark  # noqa: F401

INSUFFICIENT = dict(status='insufficient_evidence', summary='관련 근거를 찾지 못했습니다.', causes=[], steps=[],
                    parts=[], evidence=[], departments=[], questions=['알람 번호는?'])


def reviewed(clients, equipment, result=None, runner=None, use=None):
    identity = submit(clients, equipment)
    assert start(clients, identity).status_code == 202
    return identity


def post(clients, who, identity, suffix, **payload):
    return clients[who].post(f'{BASE}/{identity}/{suffix}', json=payload or None)


def item(clients, who, identity):
    return clients[who].get(f'{BASE}/{identity}').json()


def approved(clients, equipment):
    identity = reviewed(clients, equipment)
    assert post(clients, 'staff', identity, 'approval').status_code == 200
    return identity


def keys(identity):
    number = identity[4:]
    return {'service': f'SVC-{number}', 'quality': f'QLT-{number}', 'parts': f'PRT-{number}', 'sales': f'SAL-{number}'}


# ---------- authorization ----------

OPERATOR_ACTIONS = [
    ('patch', 'departments/service', {'selected': False}), ('post', 'assignee', None),
    ('post', 'comments', {'kind': 'internal', 'text': '메모'}), ('post', 'approval', None),
    ('post', 'decline', {'reason': '사유'}), ('post', 'reanalysis', None),
    ('post', 'work/SVC-000/assignee', None), ('post', 'work/SVC-000/start', None),
    ('post', 'work/SVC-000/complete', {'summary': '조치'}), ('post', 'resolution', {'note': ''}),
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
    assert after['status'] == '검토 대기' and after['linked'] == [] and after['comments'] == []


# ---------- department review edits ----------

def test_department_selection_and_drafts_are_durable_and_keep_the_ai_original(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    identity = reviewed(clients, equipment)
    assert clients['staff'].patch(f'{BASE}/{identity}/departments/quality', json={'selected': True}).status_code == 200
    assert clients['staff'].patch(f'{BASE}/{identity}/departments/service', json={'draft': '수정한 점검 지시'}).status_code == 200
    assert clients['staff'].patch(f'{BASE}/{identity}/departments/parts', json={'selected': False}).status_code == 200
    with TestClient(app, cookies=clients['staff'].cookies) as fresh:
        departments = {d['key']: d for d in fresh.get(f'{BASE}/{identity}').json()['departments']}
    assert departments['service']['draft'] == '수정한 점검 지시' and departments['service']['aiDraft'] == 'ATC 점검 방문'
    assert departments['quality']['selected'] is True and departments['quality']['aiSelected'] is False
    assert departments['parts']['selected'] is False and departments['parts']['aiSelected'] is True
    assert clients['staff'].patch(f'{BASE}/{identity}/departments/service', json={'reset': True}).status_code == 200
    assert item(clients, 'staff', identity)['departments'][0]['draft'] == 'ATC 점검 방문'


@pytest.mark.parametrize('payload', [{}, {'reset': True, 'draft': 'x'}, {'draft': 'x' * 10001}, {'selected': 'maybe'},
                                      {'selected': True, 'extra': 1}, {'reset': False}])
def test_invalid_department_edits_are_rejected(setup, use_runner, payload):
    clients, equipment = setup
    use_runner(Runner())
    identity = reviewed(clients, equipment)
    assert clients['staff'].patch(f'{BASE}/{identity}/departments/service', json=payload).status_code == 422
    assert clients['staff'].patch(f'{BASE}/{identity}/departments/legal', json={'selected': True}).status_code in (404, 422)
    assert item(clients, 'staff', identity)['departments'][0]['draft'] == 'ATC 점검 방문'


def test_department_edits_are_only_allowed_while_reviewable(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    waiting = submit(clients, equipment)  # received, no analysis yet
    assert clients['staff'].patch(f'{BASE}/{waiting}/departments/service', json={'selected': True}).status_code == 409
    identity = approved(clients, equipment)
    response = clients['staff'].patch(f'{BASE}/{identity}/departments/service', json={'draft': '승인 후 변경'})
    assert response.status_code == 409 and response.json()['code'] == 'INVALID_STATE'
    declined = reviewed(clients, equipment)
    post(clients, 'staff', declined, 'decline', reason='근거 부족')
    assert clients['staff'].patch(f'{BASE}/{declined}/departments/service', json={'selected': False}).status_code == 409


# ---------- approval ----------

def test_approval_creates_work_from_the_stored_edited_drafts_once(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    identity = reviewed(clients, equipment)
    clients['staff'].patch(f'{BASE}/{identity}/departments/service', json={'draft': '검토자가 수정한 지시'})
    clients['staff'].patch(f'{BASE}/{identity}/departments/sales', json={'selected': True})
    clients['staff'].patch(f'{BASE}/{identity}/departments/sales', json={'draft': '고객 안내 초안'})
    clients['staff'].patch(f'{BASE}/{identity}/departments/parts', json={'selected': False})
    assert post(clients, 'staff', identity, 'approval', departments=['quality']).status_code == 422  # client cannot choose
    response = post(clients, 'staff', identity, 'approval')
    assert response.status_code == 200
    result = response.json()
    assert result['status'] == '처리 중'
    wanted = keys(identity)
    assert [(w['key'], w['workKey'], w['status'], w['content'], w['edited']) for w in result['linked']] == [
        ('service', wanted['service'], '전달됨', '검토자가 수정한 지시', True),
        ('sales', wanted['sales'], '전달됨', '고객 안내 초안', True)]
    assert result['approval']['by'].startswith('staff-') and result['approval']['at']
    assert [d['key'] for d in result['approval']['delivered']] == ['service', 'sales']
    assert result['assignee'] == result['approval']['by']
    assert all(w['assignee'] is None and w['result'] is None for w in result['linked'])
    assert item(clients, 'staff', identity)['linked'] == result['linked']  # durable


def test_second_approval_does_not_duplicate_or_change_work(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    identity = approved(clients, equipment)
    before = item(clients, 'staff', identity)
    again = post(clients, 'staff', identity, 'approval')
    assert again.status_code == 409 and again.json()['code'] == 'INVALID_STATE'
    assert item(clients, 'staff', identity)['linked'] == before['linked']
    with psycopg.connect(DSN) as db:
        assert db.execute('SELECT count(*) FROM service_work WHERE request_id=%s', (int(identity[4:]),)).fetchone()[0] == 2


def test_simultaneous_approvals_create_exactly_one_set_of_work(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    identity = reviewed(clients, equipment)
    def approve(_):
        with TestClient(app, cookies=clients['staff'].cookies, headers=dict(clients['staff'].headers)) as client:
            return client.post(f'{BASE}/{identity}/approval').status_code
    with ThreadPoolExecutor(4) as pool:
        codes = sorted(pool.map(approve, range(4)))
    assert codes == [200, 409, 409, 409]
    assert len(item(clients, 'staff', identity)['linked']) == 2


@pytest.mark.parametrize('prepare', ['none_selected', 'blank_draft'])
def test_approval_needs_a_selected_department_with_a_nonblank_draft(setup, use_runner, prepare):
    clients, equipment = setup
    use_runner(Runner())
    identity = reviewed(clients, equipment)
    for key in ['service', 'parts']:
        if prepare == 'none_selected':
            clients['staff'].patch(f'{BASE}/{identity}/departments/{key}', json={'selected': False})
        else:
            clients['staff'].patch(f'{BASE}/{identity}/departments/{key}', json={'draft': '   '})
    response = post(clients, 'staff', identity, 'approval')
    assert response.status_code == 409 and response.json()['code'] == 'APPROVAL_REQUIREMENTS'
    assert item(clients, 'staff', identity)['linked'] == [] and item(clients, 'staff', identity)['status'] == '검토 대기'


def test_unanalysed_request_cannot_be_approved_declined_or_given_work(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    identity = submit(clients, equipment)
    for suffix, payload in [('approval', {}), ('decline', {'reason': '사유'}), ('resolution', {'note': ''}),
                            ('reanalysis', {})]:
        assert post(clients, 'staff', identity, suffix, **payload).status_code == 409, suffix
    assert item(clients, 'staff', identity)['status'] == '접수됨'


def test_decline_requires_reason_keeps_it_internal_and_allows_reanalysis(setup, use_runner):
    clients, equipment = setup
    runner = use_runner(Runner())
    identity = reviewed(clients, equipment)
    assert post(clients, 'staff', identity, 'decline', reason='   ').status_code == 422
    assert post(clients, 'staff', identity, 'decline').status_code == 422
    assert post(clients, 'staff', identity, 'decline', reason='근거가 약합니다').status_code == 200
    staff_view = item(clients, 'staff', identity)
    assert staff_view['status'] == '반려됨'
    assert any(c['kind'] == 'internal' and c['text'] == '반려 사유: 근거가 약합니다' for c in staff_view['comments'])
    customer = item(clients, 'alice', identity)
    assert customer['status'] == '확인 중' and '근거가 약합니다' not in str(customer) and '반려' not in str(customer)
    assert post(clients, 'staff', identity, 'decline', reason='다시').status_code == 409
    assert post(clients, 'staff', identity, 'approval').status_code == 409
    assert post(clients, 'staff', identity, 'reanalysis').status_code == 202
    assert len(runner.inputs) == 2 and item(clients, 'staff', identity)['status'] == '검토 대기'


# ---------- department work and closure ----------

def test_work_follows_assign_start_complete_rules_and_closes_only_when_all_done(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    identity = approved(clients, equipment)
    wk = keys(identity)
    path = lambda key, action: f'{BASE}/{identity}/work/{wk[key]}/{action}'
    assert clients['staff'].post(path('service', 'complete'), json={'summary': '너무 이름'}).status_code == 409  # not started
    assert clients['staff'].post(path('service', 'start')).status_code == 200
    assert clients['staff'].post(path('service', 'start')).status_code == 409  # cannot restart
    assert clients['staff'].post(path('service', 'complete'), json={'summary': '  '}).status_code == 422
    assert clients['staff'].post(path('service', 'complete'), json={'summary': '모터 교체', 'hours': 'x' * 21}).status_code == 422
    done = clients['staff'].post(path('service', 'complete'), json={'summary': '모터 교체 후 정상 확인', 'hours': '2'})
    assert done.status_code == 200
    service = next(w for w in done.json()['linked'] if w['key'] == 'service')
    assert service['status'] == '완료' and service['result'] == {'summary': '모터 교체 후 정상 확인', 'hours': '2'}
    assert service['assignee'].startswith('staff-') and service['startedAt'] and service['doneAt']
    assert clients['staff'].post(path('service', 'complete'), json={'summary': '다시'}).status_code == 409
    early = post(clients, 'staff', identity, 'resolution', note='서둘러 종결')
    assert early.status_code == 409 and early.json()['code'] == 'WORK_NOT_COMPLETE'
    assert clients['staff'].post(path('parts', 'assignee')).status_code == 200
    assert clients['staff'].post(path('parts', 'assignee')).status_code == 409
    assert clients['staff'].post(path('parts', 'start')).status_code == 200
    assert clients['staff'].post(path('parts', 'complete'), json={'summary': '재고 확인 완료'}).status_code == 200
    assert clients['staff'].post(f'{BASE}/{identity}/work/NOPE-1/start').status_code == 404
    closed = post(clients, 'staff', identity, 'resolution', note='고객께 결과 안내 완료')
    assert closed.status_code == 200
    result = closed.json()
    assert result['status'] == '종결' and result['resolution']['note'] == '고객께 결과 안내 완료'
    assert result['resolution']['by'].startswith('staff-') and result['resolution']['at']
    assert post(clients, 'staff', identity, 'resolution', note='again').status_code == 409
    assert clients['staff'].post(path('service', 'start')).status_code == 409
    texts = [h['text'] for h in result['history']]
    assert any('승인 ·' in t for t in texts) and any(wk['service'] in t and '진행 시작' in t for t in texts)
    assert any(wk['service'] in t and '처리 완료' in t for t in texts) and any(t.endswith(' 종결') for t in texts)


def test_work_actions_require_an_approved_open_request(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    identity = reviewed(clients, equipment)  # not approved: no work exists
    assert clients['staff'].post(f'{BASE}/{identity}/work/{keys(identity)["service"]}/start').status_code == 404


def test_operator_assignment_is_idempotent_for_the_same_person_and_never_steals(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    identity = reviewed(clients, equipment)
    first = post(clients, 'staff', identity, 'assignee')
    assert first.status_code == 200 and first.json()['assignee'].startswith('staff-')
    assert post(clients, 'staff', identity, 'assignee').status_code == 200
    with psycopg.connect(DSN) as db:
        db.execute("UPDATE service_request SET assignee='another-operator' WHERE id=%s", (int(identity[4:]),))
    taken = post(clients, 'staff', identity, 'assignee')
    assert taken.status_code == 409 and taken.json()['code'] == 'ALREADY_ASSIGNED'


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


# ---------- customer actions ----------


# ---------- insufficient evidence, customer reply and re-analysis ----------


def test_reanalysis_replaces_recommendations_and_discards_review_edits(setup, use_runner):
    clients, equipment = setup
    runner = use_runner(Runner())
    identity = reviewed(clients, equipment)
    clients['staff'].patch(f'{BASE}/{identity}/departments/service', json={'draft': '버려질 수정'})
    runner.result = good_result(summary='새 분석', departments=[{'key': 'quality', 'reason': '재발 방지', 'draft': '품질 조사'}])
    assert post(clients, 'staff', identity, 'reanalysis').status_code == 202
    after = item(clients, 'staff', identity)
    assert after['status'] == '검토 대기' and after['revision'] == 2 and after['analysis']['summary'] == '새 분석'
    selected = {d['key']: d['selected'] for d in after['departments']}
    assert selected == {'service': False, 'quality': True, 'parts': False, 'sales': False}
    assert next(d for d in after['departments'] if d['key'] == 'quality')['draft'] == '품질 조사'
    assert any(h['text'] == '재분석 요청' for h in after['history'])


@pytest.mark.parametrize('status_setup,expected', [('received', 409), ('approved', 409), ('closed', 409)])
def test_reanalysis_is_not_available_outside_review_states(setup, use_runner, status_setup, expected):
    clients, equipment = setup
    use_runner(Runner())
    identity = submit(clients, equipment) if status_setup == 'received' else approved(clients, equipment)
    if status_setup == 'closed':
        wk = keys(identity)
        for key in ['service', 'parts']:
            clients['staff'].post(f'{BASE}/{identity}/work/{wk[key]}/start')
            clients['staff'].post(f'{BASE}/{identity}/work/{wk[key]}/complete', json={'summary': '완료'})
        post(clients, 'staff', identity, 'resolution', note='')
    assert post(clients, 'staff', identity, 'reanalysis').status_code == expected
    assert len(item(clients, 'staff', identity)['linked']) == (0 if status_setup == 'received' else 2)


def test_failed_reanalysis_restores_the_previous_review_state_and_keeps_the_old_result(setup, use_runner):
    clients, equipment = setup
    runner = use_runner(Runner())
    identity = reviewed(clients, equipment)
    clients['staff'].patch(f'{BASE}/{identity}/departments/service', json={'draft': '유지될 수정'})
    runner.error = RuntimeError('upstream down')
    assert post(clients, 'staff', identity, 'reanalysis').status_code == 202
    after = item(clients, 'staff', identity)
    assert after['status'] == '검토 대기' and after['revision'] == 1
    assert after['analysisRun'] == {'status': 'failed', 'errorCode': 'agent_error'}
    assert after['analysis']['summary'] == 'ATC 구동부 점검이 우선입니다.'
    assert next(d for d in after['departments'] if d['key'] == 'service')['draft'] == '유지될 수정'
    runner.error = None
    assert post(clients, 'staff', identity, 'reanalysis').status_code == 202


def test_orphaned_reanalysis_returns_to_its_previous_state(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner(good_result(**INSUFFICIENT)))
    identity = reviewed(clients, equipment)
    assert item(clients, 'staff', identity)['status'] == '추가 정보 필요'
    from app.service_requests import analysis as analysis_module
    with psycopg.connect(DSN) as db:
        staff = db.execute("SELECT id FROM app_user WHERE login_id LIKE 'staff-%'").fetchone()[0]
        analysis_module.begin(db, int(identity[4:]), staff, allowed=('추가 정보 필요',))
        db.execute("UPDATE service_analysis SET worker_id='previous-server-process' WHERE status='running'")
    assert item(clients, 'staff', identity)['status'] == '추가 정보 필요'


# ---------- customer projection ----------

def test_customer_view_never_contains_internal_workflow_data(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    identity = reviewed(clients, equipment)
    post(clients, 'staff', identity, 'comments', kind='internal', text='내부전용메모')
    post(clients, 'staff', identity, 'assignee')
    post(clients, 'staff', identity, 'approval')
    customer = item(clients, 'alice', identity)
    listed = next(x for x in clients['alice'].get(BASE).json()['requests'] if x['id'] == identity)
    for view in (customer, listed):
        assert view['status'] == '처리 중'
        assert not {'analysis', 'analysisRun', 'departments', 'linked', 'approval', 'assignee', 'revision', 'closeRequested'} & set(view)
        dump = str(view)
        for secret in ['내부전용메모', 'ATC 점검 방문', 'staff-', '승인 ·', '연결 업무', 'SVC-', 'ATC 암 구동']:
            assert secret not in dump, secret
    assert [h['text'] for h in customer['history']] == ['서비스 요청이 접수되었습니다.', '담당 부서에서 처리를 시작했습니다.']


def test_customer_guides_list_only_reviewed_manual_titles_without_excerpts_or_analysis(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    identity = reviewed(clients, equipment)
    assert item(clients, 'alice', identity)['guides'] == []  # unreviewed AI output is not shown to customers
    post(clients, 'staff', identity, 'approval')
    customer = item(clients, 'alice', identity)
    assert customer['guides'] == [{'id': 'E1', 'title': 'F400 매뉴얼', 'source': 'F400 매뉴얼 p.45', 'viewable': False}]  # no stored page reference
    assert 'ATC 구동부 점검' not in str(customer) and 'FSR-00001' not in str(customer)
    assert 'guides' not in item(clients, 'staff', identity)


# ---------- customers file a request and watch it; they have no follow-up actions ----------

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
    assert 'closeRequested' not in after


def test_insufficient_evidence_is_handled_by_operators_who_may_ask_publicly_and_reanalyse(setup, use_runner):
    clients, equipment = setup
    runner = use_runner(Runner(good_result(**INSUFFICIENT)))
    identity = reviewed(clients, equipment)
    staff_view = item(clients, 'staff', identity)
    assert staff_view['status'] == '추가 정보 필요' and staff_view['revision'] == 1
    assert item(clients, 'alice', identity)['status'] == '확인 중'
    assert post(clients, 'staff', identity, 'comments', kind='public', text='알람 번호를 알려주세요.').status_code == 201
    assert [c['text'] for c in item(clients, 'alice', identity)['comments']] == ['알람 번호를 알려주세요.']
    runner.result = good_result()
    assert post(clients, 'staff', identity, 'reanalysis').status_code == 202
    assert len(runner.inputs) == 2 and runner.inputs[1]['additional_info'] == [] and 'contact' not in runner.inputs[1]
    after = item(clients, 'staff', identity)
    assert after['status'] == '검토 대기' and after['revision'] == 2
    assert item(clients, 'alice', identity)['status'] == '확인 중'


def test_the_only_comments_in_the_system_are_operator_notes_and_operator_replies(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    identity = reviewed(clients, equipment)
    post(clients, 'staff', identity, 'comments', kind='internal', text='메모')
    post(clients, 'staff', identity, 'comments', kind='public', text='안내')
    assert {c['kind'] for c in item(clients, 'staff', identity)['comments']} == {'internal', 'public'}
    assert {c['kind'] for c in item(clients, 'alice', identity)['comments']} == {'public'}

"""Retired notes/replies are neither writable nor projected. Only isolated regression databases."""
import psycopg
import pytest

from test_service_analysis_api import Runner, use_runner  # noqa: F401
from test_service_requests_api import setup, BASE, DSN, pytestmark  # noqa: F401
from test_service_workflow_api import reviewed, item, post


@pytest.mark.parametrize('kind', ['internal', 'public'])
@pytest.mark.parametrize('state', ['접수됨', '처리 중', '종결'])
def test_comment_endpoint_is_gone_for_every_request_state(setup, use_runner, kind, state):
    clients, equipment = setup
    use_runner(Runner())
    from test_service_analysis_api import submit
    identity = submit(clients, equipment) if state == '접수됨' else reviewed(clients, equipment)
    if state == '종결':
        assert post(clients, 'staff', identity, 'resolution', note='처리 결과는 유지합니다.').status_code == 200
    before = item(clients, 'staff', identity)
    for who in ('staff', 'alice', 'colleague', 'bob', 'unassigned'):
        answer = post(clients, who, identity, 'comments', kind=kind, text='이 경로는 없어야 합니다.')
        assert answer.status_code in (404, 405)
    assert item(clients, 'staff', identity) == before


def test_archived_comments_never_reach_any_detail_or_list_and_result_is_preserved(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    identity = reviewed(clients, equipment)
    number = int(identity[4:])
    with psycopg.connect(DSN) as db:
        actor, login = db.execute("SELECT id,login_id FROM app_user WHERE role='admin' LIMIT 1").fetchone()
        for kind in ('internal', 'public'):
            db.execute('INSERT INTO service_legacy.service_comment(request_id,author_id,author,kind,text) VALUES (%s,%s,%s,%s,%s)',
                       (number, actor, login, kind, '옛댓글노출금지-' + kind))
    assert post(clients, 'staff', identity, 'resolution', note='고객에게 보여 줄 처리 결과').status_code == 200
    for who in ('staff', 'alice', 'colleague'):
        detail = item(clients, who, identity)
        listed = next(r for r in clients[who].get(BASE).json()['requests'] if r['id'] == identity)
        for view in (detail, listed):
            assert 'comments' not in view
            assert '옛댓글노출금지' not in str(view)
        assert detail['resolution']['note'] == '고객에게 보여 줄 처리 결과'


def test_analysis_activities_come_from_latest_result_not_retired_review_tables(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    identity = reviewed(clients, equipment)
    with psycopg.connect(DSN) as db:
        number = int(identity[4:])
        assert db.execute('SELECT count(*) FROM service_legacy.service_request_department WHERE request_id=%s', (number,)).fetchone()[0] == 0
    selected = [d for d in item(clients, 'staff', identity)['departments'] if d['aiSelected']]
    assert [d['key'] for d in selected] == ['service', 'parts']
    assert [(d['reason'], d['aiDraft']) for d in selected] == [('현장 점검 필요', 'ATC 점검 방문'), ('부품 수배', '모터 재고 확인')]

"""Retired additional-information endpoints and data stay outside the current workflow.

Real sessions/CSRF/DB in disposable regression databases only.
"""
from pathlib import Path

import psycopg
import pytest

from test_service_analysis_api import Runner, use_runner, submit, start  # noqa: F401
from test_service_requests_api import setup, BASE, DSN, pytestmark  # noqa: F401
from test_service_workflow_api import reviewed, item, post
from test_service_chat import Script, use_model, send  # noqa: F401

CALL_NOTE = '보존 전용 현장 기록: 알람 3001'


@pytest.mark.parametrize('state', ['접수됨', '처리 중', '종결'])
def test_retired_endpoint_is_absent_for_all_roles_and_states(setup, use_runner, state):
    clients, equipment = setup
    use_runner(Runner())
    identity = submit(clients, equipment) if state == '접수됨' else reviewed(clients, equipment)
    if state == '종결':
        assert post(clients, 'staff', identity, 'resolution', note='고객 처리 결과').status_code == 200
    before = item(clients, 'staff', identity)
    for who in clients:
        answer = post(clients, who, identity, 'additional-info', text=CALL_NOTE)
        assert answer.status_code in (404, 405)
    assert item(clients, 'staff', identity) == before


def archive_note(identity):
    with psycopg.connect(DSN) as db:
        actor, login = db.execute("SELECT id,login_id FROM app_user WHERE role='admin' LIMIT 1").fetchone()
        db.execute('INSERT INTO service_legacy.service_additional_info(request_id,author_id,author,text) VALUES (%s,%s,%s,%s)',
                   (int(identity[4:]), actor, login, CALL_NOTE))


def test_archived_facts_are_not_projected_or_used_for_reanalysis_or_chat(setup, use_runner):
    clients, equipment = setup
    runner = use_runner(Runner())
    identity = reviewed(clients, equipment)
    archive_note(identity)
    for who in ('staff', 'alice', 'colleague'):
        detail = item(clients, who, identity)
        listed = next(r for r in clients[who].get(BASE).json()['requests'] if r['id'] == identity)
        for view in (detail, listed):
            assert 'additionalInfo' not in view and CALL_NOTE not in str(view)
    assert post(clients, 'staff', identity, 'reanalysis').status_code == 202
    assert len(runner.inputs) == 2
    assert all('additional_info' not in request for request in runner.inputs)
    from app.service_requests import chat
    row, _ = chat._load(int(identity[4:]))
    assert CALL_NOTE not in chat.request_context(identity, row)


def test_archived_pending_proposals_cannot_be_listed_confirmed_or_cancelled(setup, use_runner):
    clients, equipment = setup
    runner = use_runner(Runner())
    identity = reviewed(clients, equipment)
    with psycopg.connect(DSN) as db:
        pid = db.execute("""INSERT INTO service_legacy.service_additional_info_proposal(id,request_id,kind,text)
            OVERRIDING SYSTEM VALUE
            VALUES (nextval(pg_get_serial_sequence('service_chat_proposal','id')),%s,'add_info',%s) RETURNING id""",
                         (int(identity[4:]), CALL_NOTE)).fetchone()[0]
    assert item(clients, 'staff', identity)['proposals'] == []
    for action in ('confirm', 'cancel'):
        response = clients['staff'].post(f'{BASE}/{identity}/proposals/{pid}/{action}', json={})
        assert response.status_code == 404 and response.json()['code'] == 'PROPOSAL_NOT_FOUND'
    assert len(runner.inputs) == 1 and 'additional_info' not in runner.inputs[0]


def test_archive_migration_preserves_all_rows_and_removes_old_proposals_from_execution(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    identity = reviewed(clients, equipment)
    number = int(identity[4:])
    migration = Path(__file__).resolve().parents[1] / 'migrations/028_archive_additional_info.sql'
    with psycopg.connect(DSN) as db:
        with db.transaction(force_rollback=True):
            # Reconstruct the pre-028 schema only in this rollback-only transaction.
            db.execute('ALTER TABLE service_legacy.service_additional_info SET SCHEMA public')
            db.execute('ALTER TABLE service_legacy.service_additional_info_proposal RENAME TO service_additional_info_proposal_before_test')
            db.execute('ALTER TABLE service_chat_proposal DROP CONSTRAINT service_chat_proposal_kind_check')
            db.execute("ALTER TABLE service_chat_proposal ADD CONSTRAINT service_chat_proposal_kind_check CHECK (kind IN ('add_info','reanalysis'))")
            actor, login = db.execute("SELECT id,login_id FROM app_user WHERE role='admin' LIMIT 1").fetchone()
            db.execute('INSERT INTO service_additional_info(request_id,author_id,author,text) VALUES (%s,%s,%s,%s)',
                       (number, actor, login, CALL_NOTE))
            old_ids = [db.execute("INSERT INTO service_chat_proposal(request_id,kind,text,status) VALUES (%s,'add_info',%s,%s) RETURNING id",
                                 (number, CALL_NOTE, status)).fetchone()[0] for status in ('pending', 'confirmed', 'cancelled')]
            current = db.execute("INSERT INTO service_chat_proposal(request_id,kind) VALUES (%s,'reanalysis') RETURNING id", (number,)).fetchone()[0]
            notes = db.execute('SELECT row_to_json(n) FROM service_additional_info n ORDER BY id').fetchall()
            old = db.execute("SELECT row_to_json(p) FROM service_chat_proposal p WHERE kind='add_info' ORDER BY id").fetchall()
            request_before = db.execute('SELECT row_to_json(r) FROM service_request r WHERE id=%s', (number,)).fetchone()
            db.execute(migration.read_text(encoding='utf-8'))
            assert db.execute("SELECT to_regclass('public.service_additional_info')").fetchone()[0] is None
            assert db.execute('SELECT row_to_json(n) FROM service_legacy.service_additional_info n ORDER BY id').fetchall() == notes
            assert db.execute('SELECT row_to_json(p) FROM service_legacy.service_additional_info_proposal p ORDER BY id').fetchall() == old
            assert not db.execute('SELECT id FROM service_chat_proposal WHERE id=ANY(%s)', (old_ids,)).fetchall()
            assert db.execute('SELECT id FROM service_chat_proposal WHERE id=%s', (current,)).fetchone()
            assert db.execute('SELECT row_to_json(r) FROM service_request r WHERE id=%s', (number,)).fetchone() == request_before
            from app.service_requests import proposals, views
            from app.auth.service import AuthError
            assert [p['kind'] for p in views.fetch_items(db, 'r.id=%s', (number,), staff=True)[0]['proposals']] == ['reanalysis']
            for pid in old_ids:
                with pytest.raises(AuthError) as error:
                    proposals._lock(db, number, pid)
                assert error.value.status_code == 404
            with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
                db.execute("INSERT INTO service_chat_proposal(request_id,kind) VALUES (%s,'add_info')", (number,))

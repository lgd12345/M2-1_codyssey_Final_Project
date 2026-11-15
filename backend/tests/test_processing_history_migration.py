"""Backfill only evidenced processing starts, without changing historical timestamps/status or sending mail."""
from pathlib import Path
from datetime import timedelta

import psycopg
import pytest

from test_service_requests_api import setup, DSN, pytestmark  # noqa: F401
from test_service_analysis_api import submit

MIGRATION = Path(__file__).resolve().parents[1] / 'migrations/027_processing_start_history.sql'
NOTICE = '담당부서에서 처리를 시작했습니다.'


@pytest.mark.parametrize('status', ['처리 중', '종결'])
@pytest.mark.parametrize('existing', [None, '처리를 시작했습니다.', '담당 부서에서 처리를 시작했습니다.', NOTICE, 'internal-only'])
def test_processing_history_backfill_is_evidenced_timestamp_preserving_and_idempotent(setup, status, existing):
    clients, equipment = setup
    number = int(submit(clients, equipment)[4:])
    with psycopg.connect(DSN) as db:
        with db.transaction(force_rollback=True):
            actor = db.execute("SELECT id FROM app_user WHERE role='admin' LIMIT 1").fetchone()[0]
            db.execute('UPDATE service_request SET status=%s WHERE id=%s', (status, number))
            started = db.execute("""INSERT INTO service_analysis(request_id,requested_by,status,previous_status,created_at,finished_at,error_code,worker_id)
                VALUES (%s,%s,'failed','접수됨',now()-interval '2 hours',now(),'agent_error','history-migration-test') RETURNING created_at""", (number, actor)).fetchone()[0]
            db.execute("""INSERT INTO service_analysis(request_id,requested_by,status,previous_status,created_at,finished_at,error_code,worker_id)
                VALUES (%s,%s,'failed','접수됨',now()-interval '1 hour',now(),'agent_error','history-migration-test')""", (number, actor))
            history_at = started + timedelta(minutes=5) if existing else started
            if existing:
                text = '처리 시작 · 분석 시작' if existing == 'internal-only' else '기존 시작 기록'
                public = None if existing == 'internal-only' else existing
                db.execute('INSERT INTO service_history(request_id,at,text,public_text) VALUES (%s,%s,%s,%s)',
                           (number, history_at, text, public))
            request_before = db.execute('SELECT row_to_json(r) FROM service_request r WHERE id=%s', (number,)).fetchone()
            mail_before = db.execute('SELECT row_to_json(m) FROM service_mail m ORDER BY id').fetchall()
            for _ in range(2):
                db.execute(MIGRATION.read_text(encoding='utf-8'))
                assert db.execute('SELECT at,public_text FROM service_history WHERE request_id=%s AND public_text=%s',
                                  (number, NOTICE)).fetchall() == [(history_at, NOTICE)]
            assert db.execute('SELECT row_to_json(r) FROM service_request r WHERE id=%s', (number,)).fetchone() == request_before
            assert db.execute('SELECT row_to_json(m) FROM service_mail m ORDER BY id').fetchall() == mail_before


@pytest.mark.parametrize('status,previous_status', [('접수됨', None), ('접수됨', '접수됨'), ('처리 중', None), ('종결', None), ('처리 중', '처리 중')])
def test_migration_never_invents_a_processing_start_without_first_analysis_evidence(setup, status, previous_status):
    clients, equipment = setup
    number = int(submit(clients, equipment)[4:])
    with psycopg.connect(DSN) as db:
        with db.transaction(force_rollback=True):
            db.execute('UPDATE service_request SET status=%s WHERE id=%s', (status, number))
            if previous_status:
                actor = db.execute("SELECT id FROM app_user WHERE role='admin' LIMIT 1").fetchone()[0]
                db.execute("""INSERT INTO service_analysis(request_id,requested_by,status,previous_status,finished_at,error_code,worker_id)
                    VALUES (%s,%s,'failed',%s,now(),'agent_error','history-migration-test')""", (number, actor, previous_status))
            before = db.execute('SELECT row_to_json(h) FROM service_history h WHERE request_id=%s ORDER BY id', (number,)).fetchall()
            db.execute(MIGRATION.read_text(encoding='utf-8'))
            assert db.execute('SELECT row_to_json(h) FROM service_history h WHERE request_id=%s ORDER BY id', (number,)).fetchall() == before

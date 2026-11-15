"""Archive migration preserves old rows. All DDL below is rolled back in the isolated worker DB."""
from pathlib import Path

import psycopg

from test_service_requests_api import setup, DSN, pytestmark  # noqa: F401
from test_service_analysis_api import submit


TABLES = ('service_comment', 'service_request_department', 'service_work')


def test_archive_migration_preserves_rows_and_current_request_data(setup):
    clients, equipment = setup
    number = int(submit(clients, equipment)[4:])
    migration = Path(__file__).resolve().parents[1] / 'migrations/026_archive_retired_workflow.sql'
    with psycopg.connect(DSN) as db:
        with db.transaction(force_rollback=True):
            # Recreate the pre-026 location only inside this rollback-only transaction.
            for table in TABLES:
                db.execute(f'ALTER TABLE service_legacy.{table} SET SCHEMA public')
            db.execute('DROP SCHEMA service_legacy')
            actor, login = db.execute("SELECT id,login_id FROM app_user WHERE role='admin' LIMIT 1").fetchone()
            db.execute("INSERT INTO service_comment(request_id,author_id,author,kind,text) VALUES (%s,%s,%s,'public','보존할 옛 답변')", (number, actor, login))
            db.execute("INSERT INTO service_request_department VALUES (%s,'service',true,true,'옛 사유','옛 AI 초안','옛 수정 초안')", (number,))
            db.execute("INSERT INTO service_work(request_id,dept,work_key,content,edited) VALUES (%s,'service',%s,'옛 업무',true)", (number, f'SVC-{number:03d}'))
            snapshots = {t: db.execute(f'SELECT row_to_json(t) FROM public.{t} t ORDER BY row_to_json(t)::text').fetchall() for t in TABLES}
            request_before = db.execute('SELECT row_to_json(r) FROM service_request r WHERE id=%s', (number,)).fetchone()
            db.execute(migration.read_text(encoding='utf-8'))
            for table in TABLES:
                assert db.execute('SELECT to_regclass(%s)', (f'public.{table}',)).fetchone()[0] is None
                assert db.execute(f'SELECT row_to_json(t) FROM service_legacy.{table} t ORDER BY row_to_json(t)::text').fetchall() == snapshots[table]
            assert db.execute('SELECT row_to_json(r) FROM service_request r WHERE id=%s', (number,)).fetchone() == request_before

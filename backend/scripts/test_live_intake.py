"""Explicitly approved current-DB acceptance test; never run in default regression.

Uses existing admin/user accounts, membership and labelled verification equipment.
Does not migrate, reset databases, provision accounts, or touch the RAG corpus.
Only its randomly namespaced requests and temporary foreign fixtures are removed.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from dotenv import load_dotenv
import psycopg
from psycopg.conninfo import conninfo_to_dict

ROOT = Path(__file__).resolve().parents[1]
APPROVED_DATABASE = 'service_poc_test'


def validate_target(dsn: str, base_url: str, approval: str | None) -> str:
    if approval != APPROVED_DATABASE or conninfo_to_dict(dsn).get('dbname') != APPROVED_DATABASE:
        raise ValueError('Explicit approval and the current database must match service_poc_test')
    url = urlsplit(base_url)
    if (url.scheme not in {'http', 'https'} or url.hostname not in {'localhost', '127.0.0.1', '::1'}
            or url.username is not None or url.password is not None or url.path not in {'', '/'}
            or url.query or url.fragment):
        raise ValueError('Only a local browser origin without credentials, path or query is allowed')
    return base_url.rstrip('/')


def assert_database(connection):
    if connection.execute('SELECT current_database()').fetchone()[0] != APPROVED_DATABASE:
        raise ValueError('Connected database differs from the approved target')


def prepare(dsn: str) -> dict:
    fixture = {'run_tag': uuid4().hex}
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        assert_database(connection)
        users = list(connection.execute("SELECT id,login_id,role,is_active FROM app_user WHERE login_id IN ('admin','user')"))
        if {row[1]: (row[2],row[3]) for row in users} != {'admin': ('admin',True), 'user': ('user',True)}:
            raise ValueError('Required existing accounts/roles are not ready')
        fixture['accounts'] = {row[1]: str(row[0]) for row in users}
        equipment = connection.execute('''SELECT e.id FROM service_equipment e
            JOIN service_company_member m ON m.company_id=e.company_id
            WHERE m.user_id=%s AND e.machine=%s AND e.serial=%s''',
            (fixture['accounts']['user'], 'E2E 검증용 장비', 'E2E-LIVE-USER-001')).fetchone()
        if not equipment:
            raise ValueError('Approved user membership/labelled verification equipment is not ready')
        fixture['user_equipment_id'] = str(equipment[0])
        fixture['company_name'] = 'E2E 타사 접근제한 검증 ' + fixture['run_tag'][:8]
        fixture['other_company_id'] = str(connection.execute(
            'INSERT INTO service_company(name) VALUES (%s) RETURNING id', (fixture['company_name'],)).fetchone()[0])
        fixture['other_serial'] = 'E2E-ACCESS-' + fixture['run_tag']
        fixture['other_equipment_id'] = str(connection.execute('''INSERT INTO service_equipment(company_id,machine,serial)
            VALUES (%s,%s,%s) RETURNING id''', (fixture['other_company_id'], 'E2E 접근제한 검증용 장비',
            fixture['other_serial'])).fetchone()[0])
    return fixture


def cleanup(dsn: str, fixture: dict) -> int:
    marker = '[LIVE-E2E:' + fixture['run_tag'] + ']'
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        assert_database(connection)
        # Never truncate, delete all of an account's requests, or reset sequences.
        removed = connection.execute('''DELETE FROM service_request
            WHERE left(message,length(%s))=%s AND created_by=ANY(%s)''',
            (marker, marker, [UUID(value) for value in fixture['accounts'].values()])).rowcount
        equipment = connection.execute('DELETE FROM service_equipment WHERE id=%s AND company_id=%s AND serial=%s',
            (fixture['other_equipment_id'], fixture['other_company_id'], fixture['other_serial']))
        if equipment.rowcount != 1:
            raise ValueError('Temporary equipment cleanup scope mismatch')
        company = connection.execute('DELETE FROM service_company WHERE id=%s AND name=%s',
            (fixture['other_company_id'], fixture['company_name']))
        if company.rowcount != 1:
            raise ValueError('Temporary company cleanup scope mismatch')
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-current-db', required=True, choices=[APPROVED_DATABASE])
    parser.add_argument('--base-url', default='http://localhost:4173')
    args = parser.parse_args()
    load_dotenv(ROOT / '.env', override=False)
    try:
        dsn = (os.getenv('RAG_DATABASE_URL', '') or os.getenv('DATABASE_URL', '')).strip()
        base_url = validate_target(dsn, args.base_url, args.allow_current_db)
        if not all(os.getenv(key) for key in ['LIVE_E2E_USER_PASSWORD', 'LIVE_E2E_ADMIN_PASSWORD']):
            raise ValueError('Supply both current-account passwords explicitly via environment')
        node = os.getenv('NODE_BINARY') or shutil.which('node')
        frontend = ROOT.parent / 'frontend'
        cli = frontend / 'node_modules/@playwright/test/cli.js'
        if not node or not cli.is_file():
            raise ValueError('Node and installed frontend Playwright dependencies are required')
        fixture = prepare(dsn)
        try:
            env = {**os.environ, 'LIVE_E2E_APPROVED_DB': APPROVED_DATABASE, 'LIVE_E2E_BASE_URL': base_url,
                   'LIVE_E2E_RUN_TAG': fixture['run_tag'],
                   'LIVE_E2E_EXPECTED_USER_ID': fixture['accounts']['user'],
                   'LIVE_E2E_EXPECTED_ADMIN_ID': fixture['accounts']['admin'],
                   'LIVE_E2E_USER_EQUIPMENT_ID': fixture['user_equipment_id'],
                   'LIVE_E2E_OTHER_EQUIPMENT_ID': fixture['other_equipment_id']}
            print('Running explicit current-DB E2E; not an isolated regression database.', flush=True)
            process = subprocess.Popen([node, str(cli), 'test', '--config', 'playwright.live.config.js'], cwd=frontend, env=env)
            try:
                return process.wait(timeout=600)
            finally:
                if process.poll() is None:
                    if os.name == 'nt':
                        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                       capture_output=True, timeout=10, check=False)
                    else:
                        process.kill()
                    process.wait(timeout=10)
        finally:
            removed = cleanup(dsn, fixture)
            print(f'Cleanup: {removed} marked test requests and temporary foreign fixtures removed; existing user setup retained.', flush=True)
    except Exception as exc:
        # Do not expose credentials, DSNs or session tokens in failure output.
        print(f'Current-DB E2E runner failed: {type(exc).__name__}', flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

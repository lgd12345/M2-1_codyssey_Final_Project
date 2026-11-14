"""Live end-to-end quality run against the running application and its current database.

Explicitly approved by --allow-current-db. Creates only requests tagged QEVAL-<random> (and temporary equipment)
for the real `user` account and removes exactly those afterwards. Never migrates, truncates or touches the corpus.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import psycopg
from dotenv import load_dotenv

from quality.e2e import run_suite_e2e
from quality.scoring import Case
from scripts.test_live_intake import APPROVED_DATABASE, validate_target

ROOT = Path(__file__).resolve().parents[1]
API = '/api/v1/service-requests'


class HttpApi:
    def __init__(self, base_url: str, login_id: str, password: str):
        self.origin = f'{urlsplit(base_url).scheme}://{urlsplit(base_url).netloc}'
        self.client = httpx.Client(base_url=base_url, timeout=60, follow_redirects=False)
        response = self.client.post('/api/v1/auth/login', json={'login_id': login_id, 'password': password},
                                    headers={'Origin': self.origin})
        if response.status_code != 200:
            raise RuntimeError(f'login failed for {login_id} (HTTP {response.status_code})')
        self.csrf = response.json()['csrf_token']

    def get(self, path: str):
        return self.client.get(f'{API}{path}')

    def post(self, path: str, json: Any = None):
        return self.client.post(f'{API}{path}', json=json, headers={'Origin': self.origin, 'X-CSRF-Token': self.csrf})

    def close(self) -> None:
        self.client.post('/api/v1/auth/logout', headers={'Origin': self.origin, 'X-CSRF-Token': self.csrf})
        self.client.close()


def run_live_e2e(cases: list[Case], args: argparse.Namespace) -> list[dict[str, Any]]:
    load_dotenv(ROOT / '.env', override=False)
    dsn = (os.getenv('RAG_DATABASE_URL', '') or os.getenv('DATABASE_URL', '')).strip()
    base = validate_target(dsn, args.base_url, args.allow_current_db)
    passwords = {name: os.getenv(f'LIVE_E2E_{name.upper()}_PASSWORD') for name in ('user', 'admin')}
    if not all(passwords.values()):
        raise SystemExit('set LIVE_E2E_USER_PASSWORD and LIVE_E2E_ADMIN_PASSWORD')
    tag = 'QEVAL-' + uuid4().hex[:10]
    machines = sorted({case.machine for case in cases})
    equipment: dict[str, str] = {}
    with psycopg.connect(dsn, connect_timeout=5) as db:
        if db.execute('SELECT current_database()').fetchone()[0] != APPROVED_DATABASE:
            raise SystemExit('connected database differs from the approved target')
        row = db.execute("""SELECT u.id, m.company_id FROM app_user u JOIN service_company_member m ON m.user_id=u.id
                            WHERE u.login_id='user'""").fetchone()
        if not row:
            raise SystemExit("the 'user' account with a company membership is required")
        user_id, company_id = row
        for machine in machines:
            equipment[machine] = str(db.execute(
                'INSERT INTO service_equipment(company_id,machine,serial) VALUES (%s,%s,%s) RETURNING id',
                (company_id, machine, f'{tag}-{machine}')).fetchone()[0])
    apis: list[HttpApi] = []
    try:
        user_api = HttpApi(base, 'user', passwords['user'])
        apis.append(user_api)
        admin_api = HttpApi(base, 'admin', passwords['admin'])
        apis.append(admin_api)
        return run_suite_e2e(cases, user_api, admin_api, lambda machine: equipment[machine], tag=tag,
                             repeats=args.repeats, concurrency=args.concurrency, timeout=args.timeout)
    finally:
        for api in apis:
            try:
                api.close()
            except Exception:
                pass
        with psycopg.connect(dsn, connect_timeout=5) as db:
            # Tagged requests of the real user only; deleting a request cascades to its analysis, comments and history.
            removed = db.execute("DELETE FROM service_request WHERE contact->>'name'=%s AND created_by=%s",
                                 (tag, user_id)).rowcount
            db.execute('DELETE FROM service_equipment WHERE id=ANY(%s) AND serial LIKE %s', (list(equipment.values()), f'{tag}-%'))
        print(f'cleanup: removed {removed} tagged requests and {len(equipment)} temporary equipment rows ({tag})')

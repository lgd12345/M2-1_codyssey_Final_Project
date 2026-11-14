"""First vertical slice: real sessions, company isolation and durable requests.

Run ONLY through scripts/test_isolated.py. Fixtures use synthetic data in its
fresh disposable database, never in the configured corpus database.
"""
import os
from uuid import uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.auth.service import create_user

DSN = os.getenv('TEST_DATABASE_URL', '')
pytestmark = pytest.mark.skipif(not DSN, reason='isolated TEST_DATABASE_URL not configured')
PASSWORD = 'synthetic-password-for-tests'
BASE = '/api/v1/service-requests'


@pytest.fixture
def setup(monkeypatch, service_schema):
    name = conninfo_to_dict(DSN).get('dbname', '')
    if not name.startswith('rag_regression_') or not name.endswith('_test'):
        pytest.fail('Use scripts/test_isolated.py: this fixture requires a fresh disposable DB')
    monkeypatch.setenv('DATABASE_URL', DSN)
    monkeypatch.delenv('APP_COOKIE_SECURE', raising=False)
    suffix = uuid4().hex[:10]
    with psycopg.connect(DSN) as db:
        users = {role: create_user(db, f'{role}-{suffix}', PASSWORD, role='admin' if role == 'staff' else 'user')
                 for role in ['alice', 'colleague', 'bob', 'staff', 'unassigned']}
        companies = [db.execute('INSERT INTO service_company(name) VALUES (%s) RETURNING id', (f'{s}-{suffix}',)).fetchone()[0]
                     for s in ['Company A', 'Company B']]
        for who, company in [('alice', companies[0]), ('colleague', companies[0]), ('bob', companies[1]), ('staff', companies[1])]:
            db.execute('INSERT INTO service_company_member(user_id, company_id) VALUES (%s,%s)', (users[who].id, company))
        equipment = [db.execute('INSERT INTO service_equipment(machine) VALUES (%s) RETURNING id',
                               (model,)).fetchone()[0] for model in ['F400', 'F500']]
    clients = {}
    for who, user in users.items():
        client = TestClient(app)
        response = client.post('/api/v1/auth/login', json={'login_id': user.login_id, 'password': PASSWORD},
                               headers={'Origin': 'http://testserver'})
        assert response.status_code == 200
        client.headers.update({'Origin': 'http://testserver', 'X-CSRF-Token': response.json()['csrf_token']})
        clients[who] = client
    yield clients, equipment
    for client in clients.values():
        client.close()
    with psycopg.connect(DSN) as db:
        ids = [user.id for user in users.values()]
        db.execute('DELETE FROM service_request WHERE created_by=ANY(%s)', (ids,))
        db.execute('DELETE FROM service_equipment WHERE id=ANY(%s)', (equipment,))
        db.execute('DELETE FROM service_company_member WHERE user_id=ANY(%s)', (ids,))
        db.execute('DELETE FROM service_company WHERE id=ANY(%s)', (companies,))
        db.execute('DELETE FROM app_user WHERE id=ANY(%s)', (ids,))


def body(equipment):
    return {'equipment_id': str(equipment), 'reason': '공구 교환 이상', 'message': 'ATC 교환 중 멈춥니다.',
            'alarm_numbers': ['2023']}


def test_customer_intake_is_durable_visible_to_company_and_staff_not_other_company(setup):
    clients, equipment = setup
    created = clients['alice'].post(BASE, json=body(equipment[0]))
    assert created.status_code == 201
    item = created.json()
    identity = item['id']
    assert identity.startswith('CLM-')
    assert item['status'] == '접수됨'  # No pretend running/completed analysis.
    assert item['intake']['machine'] == 'F400'
    assert 'serial' not in item['intake']
    assert item['intake']['alarm'] == '2023'
    assert 'contact' not in item['intake']
    me = clients['alice'].get('/api/v1/auth/me').json()['user']['login_id']
    assert item['intake']['creator'].startswith(me + ' (')
    for who in ['alice', 'colleague', 'staff']:
        assert identity in [x['id'] for x in clients[who].get(BASE).json()['requests']]
        assert clients[who].get(f'{BASE}/{identity}').json()['intake']['symptom'] == 'ATC 교환 중 멈춥니다.'
    # New HTTP client/session proves the request is not browser-local state.
    with TestClient(app, cookies=clients['alice'].cookies) as fresh:
        assert fresh.get(f'{BASE}/{identity}').status_code == 200
    assert clients['bob'].get(BASE).json() == {'requests': []}
    assert clients['bob'].get(f'{BASE}/{identity}').status_code == 404
    assert 'analysis' not in item and 'departments' not in item and 'approval' not in item
    staff_item = clients['staff'].get(f'{BASE}/{identity}').json()
    assert staff_item['analysis'] is None
    assert staff_item['linked'] == [] and staff_item['departments'] == []
    assert 'stepsDone' not in staff_item and 'scenarioId' not in staff_item


def test_equipment_is_derived_from_authenticated_membership_not_query_or_body(setup):
    clients, equipment = setup
    context = clients['alice'].get(f'{BASE}/context?company=Company B').json()
    assert [m['id'] for m in context['equipment']] == list(map(str, equipment))
    assert context['company']['name'].startswith('Company A')
    assert len(clients['staff'].get(f'{BASE}/context').json()['equipment']) == 2
    assert clients['alice'].post(BASE, json=body(uuid4())).status_code == 404
    forged = {**body(equipment[0]), 'company': 'Company B', 'created_by': 'staff', 'createdAt': '2000-01-01'}
    assert clients['alice'].post(BASE, json=forged).status_code == 422
    assert clients['alice'].get(BASE).json() == {'requests': []}


def test_missing_membership_is_explicit_not_a_demo_company(setup):
    clients, equipment = setup
    context = clients['unassigned'].get(f'{BASE}/context').json()
    assert context == {'company': None, 'equipment': [], 'can_submit': False}
    assert clients['unassigned'].get(BASE).status_code == 403
    assert clients['unassigned'].post(BASE, json=body(equipment[0])).status_code == 403


def test_submission_requires_real_session_csrf_and_same_origin(setup):
    clients, equipment = setup
    assert TestClient(app).get(BASE).status_code == 401
    assert TestClient(app).post(BASE, json=body(equipment[0])).status_code == 401
    with TestClient(app, cookies=clients['alice'].cookies) as no_csrf:
        assert no_csrf.post(BASE, json=body(equipment[0]), headers={'Origin': 'http://testserver'}).status_code == 403
    assert clients['alice'].post(BASE, json=body(equipment[0]), headers={'Origin': 'https://evil.example'}).status_code == 403


@pytest.mark.parametrize('change', [
    {'message': '   '}, {'reason': 'unsupported'}, {'alarm_numbers': ['x' * 81]},
    {'contact': {'name': 'a', 'phone': ' '}}, {'equipment_id': 'not-a-uuid'},
    {'contact': {'name': 'a', 'phone': '010', 'email': 'invalid'}},
])
def test_invalid_intake_is_rejected_without_partial_save(setup, change):
    clients, equipment = setup
    assert clients['alice'].post(BASE, json={**body(equipment[0]), **change}).status_code == 422
    assert clients['alice'].get(BASE).json() == {'requests': []}


def test_server_allocates_unique_ids_and_staff_can_submit_for_selected_equipment(setup):
    clients, equipment = setup
    first = clients['alice'].post(BASE, json=body(equipment[0])).json()
    second = clients['staff'].post(BASE, json=body(equipment[1])).json()
    assert first['id'] != second['id']
    assert second['id'] in [x['id'] for x in clients['bob'].get(BASE).json()['requests']]
    for identity in ['CLM-000', 'CLM-9999999999999999999999999', 'not-an-id']:
        assert clients['staff'].get(f'{BASE}/{identity}').status_code == 404

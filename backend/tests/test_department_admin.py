"""Operators manage the departments mail can go to and their addresses (DB data, not server settings).

Real sessions/CSRF/DB. Run ONLY through scripts/test_isolated.py (disposable DB).
"""
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import app
from test_service_requests_api import setup, BASE, DSN, pytestmark  # noqa: F401
from test_mail_drafts import DEV

URL = f'{BASE}/departments'


@pytest.fixture
def clean(setup):
    clients, _ = setup
    yield clients
    with psycopg.connect(DSN) as db:
        db.execute("DELETE FROM service_department WHERE key NOT IN ('service','quality','parts','sales')")
        db.execute("UPDATE service_department SET recipients=ARRAY[%s], active=TRUE, updated_by=NULL, updated_at=NULL", (DEV,))
        db.execute("UPDATE service_department SET name='서비스' WHERE key='service'")


def manage(clients):
    return clients['staff'].get(f'{URL}/manage')


def test_operators_see_every_department_with_addresses_and_state(clean):
    answer = manage(clean)
    assert answer.status_code == 200
    rows = {d['key']: d for d in answer.json()['departments']}
    assert {'service', 'quality', 'parts', 'sales'} <= set(rows)  # others may exist: the browser tests share this database
    assert rows['service'] == {'key': 'service', 'name': '서비스', 'description': rows['service']['description'],
                               'recipients': [DEV], 'active': True, 'updatedBy': None, 'updatedAt': None}


def test_editing_recipients_normalises_them_and_records_who_changed_it(clean):
    answer = clean['staff'].patch(f'{URL}/service', json={'recipients': ['Field@Example.COM', ' second@example.com ', 'field@example.com']})
    assert answer.status_code == 200
    row = {d['key']: d for d in answer.json()['departments']}['service']
    assert row['recipients'] == ['field@example.com', 'second@example.com'] and row['updatedBy'].startswith('staff') and row['updatedAt']
    assert {d['key']: d for d in manage(clean).json()['departments']}['service']['recipients'] == ['field@example.com', 'second@example.com']


def test_name_description_and_active_can_be_changed_separately(clean):
    assert clean['staff'].patch(f'{URL}/quality', json={'name': '품질보증', 'description': '새 설명'}).status_code == 200
    assert clean['staff'].patch(f'{URL}/quality', json={'active': False}).status_code == 200
    row = {d['key']: d for d in manage(clean).json()['departments']}['quality']
    assert (row['name'], row['description'], row['active'], row['recipients']) == ('품질보증', '새 설명', False, [DEV])
    # The list the agent and the mail window use skips inactive departments.
    assert 'quality' not in {d['key'] for d in clean['staff'].get(URL).json()['departments']}


@pytest.mark.parametrize('payload', [
    {}, {'recipients': ['not-an-address']}, {'recipients': ['a@b.com', 'bad']}, {'recipients': ['x@y.com'] * 0 + [f'u{i}@example.com' for i in range(11)]},
    {'recipients': 'a@example.com'}, {'name': ''}, {'name': 'x' * 41}, {'description': 'x' * 301}, {'active': 'yes'},
    {'recipients': ['a@example.com'], 'key': 'other'}, {'recipients': ['a@example.com\nBcc: evil@example.com']},
])
def test_invalid_changes_are_rejected_and_change_nothing(clean, payload):
    assert clean['staff'].patch(f'{URL}/service', json=payload).status_code == 422
    row = {d['key']: d for d in manage(clean).json()['departments']}['service']
    assert row['recipients'] == [DEV] and row['name'] == '서비스'


def test_an_empty_recipient_list_is_allowed_and_blocks_mail_to_that_department(clean):
    assert clean['staff'].patch(f'{URL}/parts', json={'recipients': []}).status_code == 200
    listed = {d['key']: d for d in clean['staff'].get(URL).json()['departments']}
    assert listed['parts']['hasRecipient'] is False


def test_a_new_department_can_be_added_and_a_duplicate_key_is_refused(clean):
    made = clean['staff'].post(URL, json={'key': 'supplier', 'name': '협력사 대응', 'description': '부품업체·조립업체 책임 건',
                                         'recipients': ['partner@example.com']})
    assert made.status_code == 201
    row = {d['key']: d for d in made.json()['departments']}['supplier']
    assert row['recipients'] == ['partner@example.com'] and row['active'] is True and row['updatedBy'].startswith('staff')
    assert clean['staff'].post(URL, json={'key': 'supplier', 'name': 'x', 'description': '', 'recipients': []}).status_code == 409


@pytest.mark.parametrize('key', ['', 'A', '1abc', 'a b', 'a' * 32, 'service/../x', '../x'])
def test_a_bad_key_is_refused(clean, key):
    assert clean['staff'].post(URL, json={'key': key, 'name': '이름', 'description': '', 'recipients': []}).status_code in (404, 405, 422)


def test_unknown_departments_are_not_found_and_nothing_can_be_deleted(clean):
    assert clean['staff'].patch(f'{URL}/legal', json={'active': False}).status_code == 404
    assert clean['staff'].delete(f'{URL}/service').status_code in (404, 405)
    assert 'service' in {d['key'] for d in manage(clean).json()['departments']}


@pytest.mark.parametrize('who', ['alice', 'colleague', 'bob'])
def test_customers_cannot_read_or_change_departments(clean, who):
    assert clean[who].get(f'{URL}/manage').status_code == 403
    assert clean[who].patch(f'{URL}/service', json={'recipients': ['x@example.com']}).status_code == 403
    assert clean[who].post(URL, json={'key': 'abc', 'name': 'n', 'description': '', 'recipients': []}).status_code == 403
    assert {d['key']: d for d in manage(clean).json()['departments']}['service']['recipients'] == [DEV]


def test_session_csrf_and_origin_are_required_to_change(clean):
    body = {'recipients': ['x@example.com']}
    assert TestClient(app).patch(f'{URL}/service', json=body).status_code == 401
    assert TestClient(app).get(f'{URL}/manage').status_code == 401
    with TestClient(app, cookies=clean['staff'].cookies) as no_csrf:
        assert no_csrf.patch(f'{URL}/service', json=body, headers={'Origin': 'http://testserver'}).status_code == 403
    assert clean['staff'].patch(f'{URL}/service', json=body, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert {d['key']: d for d in manage(clean).json()['departments']}['service']['recipients'] == [DEV]


def test_the_new_address_is_what_the_mail_window_shows(clean):
    from test_service_analysis_api import submit, Runner, use_runner  # noqa: F401
    clients = clean
    equipment = None
    with psycopg.connect(DSN) as db:
        equipment = [r[0] for r in db.execute("SELECT id FROM service_equipment WHERE machine='F400'").fetchall()]
    assert clean['staff'].patch(f'{URL}/service', json={'recipients': ['dispatch@example.com']}).status_code == 200
    identity = clients['alice'].post(BASE, json={'equipment_id': str(equipment[0]), 'reason': '공구 교환 이상',
                                                 'message': 'ATC 정지', 'alarm_numbers': []}).json()['id']
    data = clients['staff'].get(f'{BASE}/{identity}/mail-template', params={'department_key': 'service'}).json()
    assert data['recipients'] == ['dispatch@example.com']

"""Fixed-template status mails to the customer who filed the request, queued in the database and sent after commit.

Real sessions/CSRF/DB; the SMTP transport is a recording double (see conftest). Run ONLY through scripts/test_isolated.py.
"""
import threading
import time
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.auth.service import create_user
from app.mail.deps import get_mail_sender
from app.mail import outbox
from app.main import app
from test_service_analysis_api import Runner, good_result, use_runner, start  # noqa: F401
from test_service_requests_api import setup, body, BASE, DSN, PASSWORD, pytestmark  # noqa: F401
from test_service_workflow_api import item, post  # noqa: F401


@pytest.fixture
def mailer(recorded_mail, setup):
    """An extra customer whose login is an e-mail address (the only kind of account that can be mailed)."""
    clients, equipment = setup
    login = f'mail-{uuid4().hex[:8]}@example.com'
    with psycopg.connect(DSN) as db:
        user = create_user(db, login, PASSWORD, role='user')
        company = db.execute('SELECT company_id FROM service_company_member LIMIT 1').fetchone()[0]
        db.execute('INSERT INTO service_company_member(user_id, company_id) VALUES (%s,%s)', (user.id, company))
    client = TestClient(app)
    response = client.post('/api/v1/auth/login', json={'login_id': login, 'password': PASSWORD},
                           headers={'Origin': 'http://testserver'})
    assert response.status_code == 200
    client.headers.update({'Origin': 'http://testserver', 'X-CSRF-Token': response.json()['csrf_token']})
    yield client, login, clients, equipment
    client.close()
    with psycopg.connect(DSN) as db:
        db.execute('DELETE FROM service_request WHERE created_by=%s', (user.id,))
        db.execute('DELETE FROM service_company_member WHERE user_id=%s', (user.id,))
        db.execute('DELETE FROM app_user WHERE id=%s', (user.id,))


def rows(identity):
    with psycopg.connect(DSN) as db:
        return db.execute('SELECT kind,status,recipient,error_code,attempts FROM service_mail WHERE request_id=%s ORDER BY id',
                          (int(identity[4:]),)).fetchall()


def file_request(mailer):
    client, login, clients, equipment = mailer
    created = client.post(BASE, json=body(equipment[0]))
    assert created.status_code == 201
    return created.json()['id']


def test_receipt_mail_is_sent_to_the_requester_with_request_facts_only(mailer, recorded_mail):
    identity = file_request(mailer)
    _, login, _, _ = mailer
    assert rows(identity) == [('received', 'sent', login, None, 1)]
    [message] = recorded_mail.messages
    assert message['To'] == login and identity in message['Subject']
    text = message.get_content()
    assert 'F400' in text and '공구 교환 이상' in text
    assert 'ATC 교환 중 멈춥니다' not in text and '2023' not in text  # the customer's own text is not echoed


def test_account_without_an_email_address_is_recorded_as_skipped_and_nothing_is_sent(setup, recorded_mail):
    clients, equipment = setup
    identity = clients['alice'].post(BASE, json=body(equipment[0])).json()['id']
    assert [(kind, status, error) for kind, status, _, error, _ in rows(identity)] == [('received', 'skipped', 'no_address')]
    assert recorded_mail.messages == []


def test_processing_and_closure_mails_follow_the_workflow_once_each(mailer, recorded_mail, use_runner):
    client, login, clients, equipment = mailer
    use_runner(Runner(good_result()))
    identity = file_request(mailer)
    assert start(clients, identity).status_code == 202  # the request becomes 처리 중: the customer is told once
    assert [(kind, status) for kind, status, *_ in rows(identity)] == [('received', 'sent'), ('approved', 'sent')]
    assert post(clients, 'staff', identity, 'reanalysis').status_code == 202  # a re-analysis does not announce it again
    assert [kind for kind, *_ in rows(identity)] == ['received', 'approved']
    assert post(clients, 'staff', identity, 'resolution', note='센서를 재조임했습니다.').status_code == 200
    assert [(kind, status) for kind, status, *_ in rows(identity)] == [
        ('received', 'sent'), ('approved', 'sent'), ('resolved', 'sent')]
    assert all(identity in m['Subject'] for m in recorded_mail.messages) and len(recorded_mail.messages) == 3
    assert '센서를 재조임했습니다.' in recorded_mail.messages[-1].get_content()
    assert all(m['To'] == login for m in recorded_mail.messages)


def test_an_internal_action_sends_nothing(mailer, recorded_mail, use_runner):
    client, login, clients, equipment = mailer
    use_runner(Runner(good_result()))
    identity = file_request(mailer)
    assert start(clients, identity).status_code == 202
    assert post(clients, 'staff', identity, 'reanalysis').status_code == 202
    assert post(clients, 'staff', identity, 'reanalysis').status_code == 202
    assert [kind for kind, *_ in rows(identity)] == ['received', 'approved']  # only the start of processing, once


def test_a_kind_is_queued_once_per_request(mailer, recorded_mail):
    identity = file_request(mailer)
    with psycopg.connect(DSN) as db:
        outbox.enqueue(db, int(identity[4:]), 'received')
        outbox.enqueue(db, int(identity[4:]), 'received')
    assert [kind for kind, *_ in rows(identity)] == ['received']


def test_transport_failure_never_breaks_the_request_and_stores_no_error_text(mailer, recorded_mail):
    recorded_mail.error = RuntimeError('535 password abcdefghijklmnop rejected for customer@example.com')
    client, login, clients, equipment = mailer
    created = client.post(BASE, json=body(equipment[0]))
    assert created.status_code == 201
    [(kind, status, recipient, error, attempts)] = rows(created.json()['id'])
    assert (kind, status, error, attempts) == ('received', 'failed', 'send_failed', 1)
    assert 'abcdefghijklmnop' not in str(created.json()) and 'rejected' not in str(created.json())
    with psycopg.connect(DSN) as db:
        stored = db.execute('SELECT * FROM service_mail').fetchall()
    assert 'abcdefghijklmnop' not in str(stored) and 'rejected' not in str(stored)


def test_mail_switched_off_changes_nothing_else(mailer):
    app.dependency_overrides[get_mail_sender] = lambda: None
    identity = file_request(mailer)
    assert rows(identity) == []


def test_operators_see_delivery_state_but_customers_do_not(mailer, recorded_mail):
    client, login, clients, equipment = mailer
    identity = file_request(mailer)
    mail = item(clients, 'staff', identity)['mail']
    assert [(entry['kind'], entry['status']) for entry in mail] == [('received', 'sent')]
    assert login not in str(mail)  # state only; the address stays in the outbox
    assert 'mail' not in client.get(f'{BASE}/{identity}').json()


def test_pending_rows_are_sent_exactly_once_even_when_two_dispatchers_race(mailer, recorded_mail):
    recorded_mail.delay = 0.3
    app.dependency_overrides[get_mail_sender] = lambda: None  # file the request without sending
    identity = file_request(mailer)
    app.dependency_overrides[get_mail_sender] = lambda: recorded_mail
    with psycopg.connect(DSN) as db:
        outbox.enqueue(db, int(identity[4:]), 'received')
    threads = [threading.Thread(target=outbox.dispatch, args=(recorded_mail, DSN)) for _ in range(2)]
    [thread.start() for thread in threads]
    [thread.join() for thread in threads]
    assert len(recorded_mail.messages) == 1
    assert [(kind, status, attempts) for kind, status, _, _, attempts in rows(identity)] == [('received', 'sent', 1)]


def test_a_row_stuck_in_sending_after_a_crash_is_failed_not_resent(mailer, recorded_mail):
    app.dependency_overrides[get_mail_sender] = lambda: None
    identity = file_request(mailer)
    with psycopg.connect(DSN) as db:
        outbox.enqueue(db, int(identity[4:]), 'received')
        db.execute("UPDATE service_mail SET status='sending', claimed_at=now() - interval '1 hour' WHERE request_id=%s",
                   (int(identity[4:]),))
    outbox.dispatch(recorded_mail, DSN)
    assert recorded_mail.messages == []
    assert [(status, error) for _, status, _, error, _ in rows(identity)] == [('failed', 'interrupted')]

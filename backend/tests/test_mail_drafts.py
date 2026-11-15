"""Department mail: the agent only drafts; nothing is sent until an operator presses send.

Real sessions/CSRF/DB; the SMTP transport is the recording double. Run ONLY through scripts/test_isolated.py.
"""
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.mail.deps import get_mail_sender
from app.service_requests import chat
from test_service_analysis_api import submit  # noqa: F401
from test_service_requests_api import setup, BASE, DSN, pytestmark  # noqa: F401
from test_service_workflow_api import item  # noqa: F401
from test_service_chat import Script, use_model, answer_after_tool, send, events, types  # noqa: F401
from test_service_chat import chat_env  # noqa: F401

DEV = 'hodob76@gmail.com'
GOOD = {'department_key': 'service', 'subject': 'CLM 출동 요청', 'body': 'F400 ATC 정지 증상입니다. 현장 점검 부탁드립니다.'}


def make(clients, identity, **change):
    return clients['staff'].post(f'{BASE}/{identity}/mail-drafts', json={**GOOD, **change})


def drafts(identity):
    with psycopg.connect(DSN) as db:
        return db.execute('SELECT id,department_key,status,sent_by_login,error_code FROM service_mail_draft '
                          'WHERE request_id=%s ORDER BY id', (int(identity[4:]),)).fetchall()


@pytest.fixture
def env(chat_env, recorded_mail):
    clients, identity = chat_env
    yield clients, identity, recorded_mail
    with psycopg.connect(DSN) as db:
        db.execute("UPDATE service_department SET recipients=ARRAY[%s], active=TRUE", (DEV,))


# ---------- departments ----------

def test_four_departments_exist_with_a_development_recipient_and_the_api_hides_addresses(env):
    clients, identity, _ = env
    answer = clients['staff'].get(f'{BASE}/departments')
    assert answer.status_code == 200
    rows = {d['key']: d for d in answer.json()['departments']}
    assert set(rows) == {'service', 'quality', 'parts', 'sales'}
    assert rows['service']['name'] == '서비스' and rows['service']['description'] and rows['service']['hasRecipient'] is True
    assert DEV not in answer.text and '@' not in answer.text
    assert clients['alice'].get(f'{BASE}/departments').status_code == 403


def test_the_agent_can_list_departments_without_seeing_any_address(env):
    clients, identity, _ = env
    use_model(Script(answer_after_tool('list_departments', {}, '서비스와 품질 부서가 있습니다.')))
    response = send(clients, identity)
    out = next(e for e in events(response) if isinstance(e, dict) and e['type'] == 'tool-output-available')['output']
    assert {d['key'] for d in out['departments']} == {'service', 'quality', 'parts', 'sales'}
    assert '@' not in str(out) and DEV not in response.text


# ---------- drafts ----------

def test_an_operator_draft_is_stored_and_sends_nothing(env):
    clients, identity, mail = env
    answer = make(clients, identity)
    assert answer.status_code == 201
    view = item(clients, 'staff', identity)['mailDrafts']
    assert [(d['department'], d['status'], d['subject']) for d in view] == [('service', 'draft', GOOD['subject'])]
    assert view[0]['departmentName'] == '서비스' and view[0]['body'] == GOOD['body'] and view[0]['recipientCount'] == 1
    assert DEV not in str(view) and mail.messages == []
    assert 'mailDrafts' not in item(clients, 'alice', identity)


def test_the_agent_tool_drafts_but_has_no_way_to_send(env):
    clients, identity, mail = env
    assert 'send_mail' not in chat.TOOL_NAMES and 'draft_department_mail' in chat.TOOL_NAMES
    use_model(Script(answer_after_tool('draft_department_mail', GOOD, '초안을 만들었습니다. 카드에서 보내기를 눌러 주세요.')))
    response = send(clients, identity)
    out = next(e for e in events(response) if isinstance(e, dict) and e['type'] == 'tool-output-available')['output']
    assert out['status'] == 'draft' and out['draft_id'] and '발송되지 않았습니다' in out['note']
    assert [d[2] for d in drafts(identity)] == ['draft'] and mail.messages == []


@pytest.mark.parametrize('change', [
    {'department_key': 'legal'}, {'department_key': ''}, {'subject': ''}, {'subject': '줄\n바꿈'},
    {'subject': 'x' * 151}, {'body': ''}, {'body': '   '}, {'body': 'x' * 4001},
    {'body': '담당 작업자는 EMP-0003 입니다'},          # pseudonymised worker IDs never go into a mail
    {'recipients': ['evil@example.com']}, {'to': 'evil@example.com'},   # the model/browser cannot choose addresses
])
def test_invalid_drafts_are_rejected(env, change):
    clients, identity, _ = env
    assert make(clients, identity, **change).status_code == 422
    assert drafts(identity) == []


def test_a_deactivated_or_addressless_department_cannot_be_drafted_for(env):
    clients, identity, _ = env
    with psycopg.connect(DSN) as db:
        db.execute("UPDATE service_department SET active=FALSE WHERE key='sales'")
        db.execute("UPDATE service_department SET recipients='{}' WHERE key='parts'")
    assert make(clients, identity, department_key='sales').status_code == 422
    assert make(clients, identity, department_key='parts').status_code == 422


# ---------- sending ----------

def test_send_is_only_possible_through_the_button_api_and_records_who_and_when(env):
    clients, identity, mail = env
    draft = make(clients, identity).json()['id']
    sent = clients['staff'].post(f'{BASE}/{identity}/mail-drafts/{draft}/send', json={})
    assert sent.status_code == 200 and sent.json()['status'] == 'sent'
    [message] = mail.messages
    assert message['To'] == DEV and message['Subject'] == GOOD['subject'] and GOOD['body'] in message.get_content()
    assert drafts(identity)[0][2] == 'sent' and drafts(identity)[0][3].startswith('staff')
    view = item(clients, 'staff', identity)
    assert any(f'메일 발송 · 서비스' in h['text'] and 'staff' in h['text'] for h in view['history'])
    assert 'EMP-' not in message.get_content()
    assert clients['staff'].post(f'{BASE}/{identity}/mail-drafts/{draft}/send', json={}).status_code == 409  # never twice
    assert len(mail.messages) == 1


def test_the_operator_may_edit_the_text_in_the_card_and_the_edited_text_is_what_goes_out(env):
    clients, identity, mail = env
    draft = make(clients, identity).json()['id']
    sent = clients['staff'].post(f'{BASE}/{identity}/mail-drafts/{draft}/send',
                                 json={'subject': '수정한 제목', 'body': '수정한 본문입니다.'})
    assert sent.status_code == 200
    assert (mail.messages[0]['Subject'], mail.messages[0].get_content().strip()) == ('수정한 제목', '수정한 본문입니다.')
    bad = make(clients, identity).json()['id']
    assert clients['staff'].post(f'{BASE}/{identity}/mail-drafts/{bad}/send', json={'body': 'EMP-0003'}).status_code == 422
    assert len(mail.messages) == 1


def test_a_failed_transport_is_recorded_without_its_text_and_can_be_retried_by_pressing_again(env):
    clients, identity, mail = env
    mail.error = RuntimeError('535 password abcdefghijklmnop rejected')
    draft = make(clients, identity).json()['id']
    answer = clients['staff'].post(f'{BASE}/{identity}/mail-drafts/{draft}/send', json={})
    assert answer.status_code == 502 and answer.json()['code'] == 'MAIL_FAILED' and 'abcdefghijklmnop' not in answer.text
    assert drafts(identity)[0][2:] == ('failed', None, 'send_failed')
    mail.error = None
    assert clients['staff'].post(f'{BASE}/{identity}/mail-drafts/{draft}/send', json={}).status_code == 200
    assert drafts(identity)[0][2] == 'sent' and len(mail.messages) == 1


def test_cancel_and_mail_switched_off_and_missing_address(env):
    clients, identity, mail = env
    one = make(clients, identity).json()['id']
    assert clients['staff'].post(f'{BASE}/{identity}/mail-drafts/{one}/cancel', json={}).status_code == 200
    assert clients['staff'].post(f'{BASE}/{identity}/mail-drafts/{one}/send', json={}).status_code == 409
    two = make(clients, identity).json()['id']
    app.dependency_overrides[get_mail_sender] = lambda: None
    off = clients['staff'].post(f'{BASE}/{identity}/mail-drafts/{two}/send', json={})
    assert off.status_code == 503 and off.json()['code'] == 'MAIL_OFF' and drafts(identity)[1][2] == 'draft'
    app.dependency_overrides[get_mail_sender] = lambda: mail
    with psycopg.connect(DSN) as db:
        db.execute("UPDATE service_department SET recipients='{}' WHERE key='service'")
    gone = clients['staff'].post(f'{BASE}/{identity}/mail-drafts/{two}/send', json={})
    assert gone.status_code == 409 and gone.json()['code'] == 'NO_RECIPIENT' and mail.messages == []


def test_a_draft_belongs_to_its_request(env):
    clients, identity, mail = env
    draft = make(clients, identity).json()['id']
    assert clients['staff'].post(f'{BASE}/CLM-999999/mail-drafts/{draft}/send', json={}).status_code == 404
    assert clients['staff'].post(f'{BASE}/{identity}/mail-drafts/999999/send', json={}).status_code == 404
    assert mail.messages == []


@pytest.mark.parametrize('who', ['alice', 'colleague', 'bob'])
@pytest.mark.parametrize('suffix', ['mail-drafts', 'mail-drafts/1/send', 'mail-drafts/1/cancel'])
def test_customers_cannot_draft_send_or_cancel(env, who, suffix):
    clients, identity, mail = env
    assert clients[who].post(f'{BASE}/{identity}/{suffix}', json={**GOOD}).status_code == 403
    assert drafts(identity) == [] and mail.messages == []


def test_session_csrf_and_origin_are_required_to_send(env):
    clients, identity, mail = env
    draft = make(clients, identity).json()['id']
    url = f'{BASE}/{identity}/mail-drafts/{draft}/send'
    assert TestClient(app).post(url, json={}).status_code == 401
    with TestClient(app, cookies=clients['staff'].cookies) as no_csrf:
        assert no_csrf.post(url, json={}, headers={'Origin': 'http://testserver'}).status_code == 403
    assert clients['staff'].post(url, json={}, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert mail.messages == []


def test_drafts_never_change_the_request_status(env):
    clients, identity, _ = env
    before = item(clients, 'staff', identity)['status']
    draft = make(clients, identity).json()['id']
    clients['staff'].post(f'{BASE}/{identity}/mail-drafts/{draft}/send', json={})
    assert item(clients, 'staff', identity)['status'] == before

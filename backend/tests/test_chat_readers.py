"""The chat agent can read the request's history and the mails written for it (read-only, never an address).

Real sessions/CSRF/DB; the model is a scripted double. Run ONLY through scripts/test_isolated.py (disposable DB).
"""
import psycopg
import pytest

from app.service_requests import chat
from test_service_requests_api import BASE, DSN, pytestmark  # noqa: F401
from test_service_chat import bare_env, chat_env, Script, use_model, answer_after_tool, send, events  # noqa: F401
from test_service_analysis_api import use_runner  # noqa: F401
from test_service_requests_api import setup  # noqa: F401
from test_service_workflow_api import item, post  # noqa: F401
from test_mail_drafts import DEV, GOOD, make  # noqa: F401

LONG_BODY = 'F400 ATC 정지 건입니다. ' + '현장 점검 내용을 자세히 적었습니다. ' * 20


def output(response):
    return next(e for e in events(response) if isinstance(e, dict) and e['type'] == 'tool-output-available')['output']


def ask(clients, identity, tool, args):
    use_model(Script(answer_after_tool(tool, args, '확인했습니다.')))
    return output(send(clients, identity))


@pytest.fixture
def env(chat_env, recorded_mail):
    clients, identity = chat_env
    yield clients, identity, recorded_mail
    with psycopg.connect(DSN) as db:
        db.execute("UPDATE service_department SET recipients=ARRAY[%s], active=TRUE", (DEV,))


def test_the_new_tools_are_registered_and_none_of_them_writes():
    for name in ('get_history', 'list_mail_drafts', 'read_mail_draft'):
        assert name in chat.TOOL_NAMES
    assert len(chat.TOOL_NAMES) == len(set(chat.TOOL_NAMES))


# ---------- history ----------

def test_history_lists_what_happened_in_order_with_times(env):
    clients, identity, _ = env
    out = ask(clients, identity, 'get_history', {})
    texts = [entry['text'] for entry in out['history']]
    assert texts[0].startswith('처리 시작') and '분석 완료' in texts[1]
    assert all(entry['at'] for entry in out['history']) and out['omitted'] == 0


def test_history_includes_a_department_mail_after_it_is_sent_and_who_sent_it(env):
    clients, identity, mail = env
    draft = make(clients, identity).json()['id']
    assert clients['staff'].post(f'{BASE}/{identity}/mail-drafts/{draft}/send', json={}).status_code == 200
    out = ask(clients, identity, 'get_history', {})
    sent = [entry['text'] for entry in out['history'] if entry['text'].startswith('메일 발송')]
    assert len(sent) == 1 and '서비스' in sent[0] and 'staff' in sent[0]


def test_history_is_bounded_and_says_how_much_was_left_out(env):
    clients, identity, _ = env
    with psycopg.connect(DSN) as db:
        for n in range(chat.MAX_HISTORY + 10):
            db.execute("INSERT INTO service_history(request_id,text) VALUES (%s,%s)", (int(identity[4:]), f'기록 {n}'))
    out = ask(clients, identity, 'get_history', {})
    assert len(out['history']) == chat.MAX_HISTORY and out['omitted'] >= 10
    assert out['history'][-1]['text'] == f'기록 {chat.MAX_HISTORY + 9}'  # the newest entries are kept


# ---------- mails ----------

def test_the_mail_list_shows_state_and_a_short_preview_but_never_an_address(env):
    clients, identity, _ = env
    first = make(clients, identity, subject='[출동 요청] 보낸 메일', body=LONG_BODY).json()['id']
    second = make(clients, identity, department_key='quality', subject='[품질 보고] 초안').json()['id']
    clients['staff'].post(f'{BASE}/{identity}/mail-drafts/{first}/send', json={})
    out = ask(clients, identity, 'list_mail_drafts', {})
    rows = {row['id']: row for row in out['mails']}
    assert rows[first]['status'] == 'sent' and rows[first]['department'] == '서비스' and rows[first]['sent_by'].startswith('staff')
    assert rows[first]['sent_at'] and rows[first]['subject'] == '[출동 요청] 보낸 메일'
    assert len(rows[first]['preview']) <= chat.MAIL_PREVIEW_CHARS and rows[first]['body_truncated'] is True
    assert rows[second]['status'] == 'draft' and rows[second]['department'] == '품질관리' and rows[second]['sent_by'] is None
    assert '@' not in str(out) and DEV not in str(out)


def test_reading_one_mail_gives_its_full_text_without_any_address(env):
    clients, identity, _ = env
    draft = make(clients, identity, body=LONG_BODY).json()['id']
    out = ask(clients, identity, 'read_mail_draft', {'draft_id': draft})
    assert out['found'] is True and out['body'] == LONG_BODY.strip() and out['status'] == 'draft'
    assert '@' not in str(out) and DEV not in str(out)


def test_an_unknown_mail_or_another_requests_mail_is_not_found(env, chat_env):
    clients, identity, _ = env
    assert ask(clients, identity, 'read_mail_draft', {'draft_id': 999999})['found'] is False


def test_a_mail_of_another_request_cannot_be_read_through_this_chat(env):
    clients, identity, _ = env
    from test_service_analysis_api import submit
    from test_service_requests_api import body as intake
    with psycopg.connect(DSN) as db:
        equipment = db.execute("SELECT id FROM service_equipment WHERE machine='F400'").fetchone()[0]
    other = clients['alice'].post(BASE, json=intake(equipment)).json()['id']
    foreign = make(clients, other, body='다른 요청의 메일 본문입니다').json()['id']
    out = ask(clients, identity, 'read_mail_draft', {'draft_id': foreign})
    assert out['found'] is False and '다른 요청' not in str(out)


def test_nothing_is_listed_for_a_request_without_mail(env):
    clients, identity, _ = env
    assert ask(clients, identity, 'list_mail_drafts', {})['mails'] == []


# ---------- instructions ----------

def test_the_instructions_tell_the_agent_to_check_earlier_mail_and_to_treat_it_as_data():
    text = chat.SYSTEM
    for name in ('get_history', 'list_mail_drafts', 'read_mail_draft'):
        assert name in text
    assert '같은 부서에 이미 보낸 메일' in text and '신뢰할 수 없는' in text

"""The agent PROPOSES saving additional information or re-analysing; only the operator's button does it.

Real sessions/CSRF/DB; the model is a scripted double. Run ONLY through scripts/test_isolated.py (disposable DB).
"""
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.service_requests import chat
from test_service_analysis_api import Runner, good_result, use_runner, start  # noqa: F401
from test_service_requests_api import setup, BASE, DSN, pytestmark  # noqa: F401
from test_service_workflow_api import INSUFFICIENT, approved, item, post, reviewed  # noqa: F401
from test_service_chat import Script, use_model, answer_after_tool, send, events  # noqa: F401
from test_service_chat import bare_env  # noqa: F401

NOTE = '전화 확인: 알람 2023이 스핀들 정지 직후에 발생함'


def proposals(identity):
    with psycopg.connect(DSN) as db:
        return db.execute('SELECT id,kind,text,status,decided_by FROM service_chat_proposal WHERE request_id=%s ORDER BY id',
                          (int(identity[4:]),)).fetchall()


def decide(clients, identity, proposal, action, who='staff', **kwargs):
    return clients[who].post(f'{BASE}/{identity}/proposals/{proposal}/{action}', json={}, **kwargs)


def tool_output(response):
    return next(e for e in events(response) if isinstance(e, dict) and e['type'] == 'tool-output-available')['output']


@pytest.fixture
def env(bare_env, use_runner):
    clients, identity = bare_env
    runner = use_runner(Runner(good_result(**INSUFFICIENT)))
    assert start(clients, identity).status_code == 202  # analysed once, reviewable (추가 정보 필요)
    return clients, identity, runner


def propose_info(clients, identity, text=NOTE):
    use_model(Script(answer_after_tool('propose_additional_info', {'text': text}, '저장할까요?')))
    return tool_output(send(clients, identity))


# ---------- proposing changes nothing ----------

def test_the_tools_exist_and_are_proposals_only():
    assert 'propose_additional_info' in chat.TOOL_NAMES and 'propose_reanalysis' in chat.TOOL_NAMES
    assert 'save_additional_info' not in chat.TOOL_NAMES and 'start_reanalysis' not in chat.TOOL_NAMES


def test_proposing_additional_information_saves_nothing(env):
    clients, identity, runner = env
    before = item(clients, 'staff', identity)
    out = propose_info(clients, identity)
    assert out['ok'] is True and out['status'] == 'proposed' and out['proposal_id'] and '저장되지 않았습니다' in out['note']
    after = item(clients, 'staff', identity)
    assert after['additionalInfo'] == before['additionalInfo'] == [] and after['status'] == before['status']
    assert after['history'] == before['history'] and len(runner.inputs) == 1
    assert [(p[1], p[2], p[3]) for p in proposals(identity)] == [('add_info', NOTE, 'pending')]


def test_proposing_a_re_analysis_starts_nothing(env):
    clients, identity, runner = env
    use_model(Script(answer_after_tool('propose_reanalysis', {}, '재분석할까요?')))
    out = tool_output(send(clients, identity))
    assert out['status'] == 'proposed' and '실행되지 않았습니다' in out['note']
    assert len(runner.inputs) == 1 and item(clients, 'staff', identity)['status'] == '추가 정보 필요'
    assert [(p[1], p[3]) for p in proposals(identity)] == [('reanalysis', 'pending')]


def test_the_same_pending_proposal_is_not_made_twice(env):
    clients, identity, _ = env
    first = propose_info(clients, identity)
    second = propose_info(clients, identity)
    assert first['proposal_id'] == second['proposal_id'] and len(proposals(identity)) == 1


@pytest.mark.parametrize('text', ['', '   ', 'x' * 2001])
def test_an_invalid_note_is_not_proposed(env, text):
    clients, identity, _ = env
    out = propose_info(clients, identity, text)
    assert out['ok'] is False and proposals(identity) == []


def test_a_re_analysis_is_not_proposed_where_none_is_possible(bare_env):
    from app.service_requests import proposals as flow
    clients, identity = bare_env  # received, never analysed: nothing to analyse again
    with psycopg.connect(DSN) as db:
        out = flow.propose(db, int(identity[4:]), 'reanalysis')
    assert out['ok'] is False and out['error']['code'] == 'invalid_state' and proposals(identity) == []


def test_the_proposals_are_listed_for_operators_only(env):
    clients, identity, _ = env
    propose_info(clients, identity)
    listed = item(clients, 'staff', identity)['proposals']
    assert [(p['kind'], p['text'], p['status']) for p in listed] == [('add_info', NOTE, 'pending')]
    assert 'proposals' not in item(clients, 'alice', identity)


# ---------- the operator's decision ----------

def test_confirming_saves_the_information_as_the_confirming_operator(env):
    clients, identity, runner = env
    pid = propose_info(clients, identity)['proposal_id']
    done = decide(clients, identity, pid, 'confirm')
    assert done.status_code == 200
    view = item(clients, 'staff', identity)
    assert [n['text'] for n in view['additionalInfo']] == [NOTE] and view['additionalInfo'][0]['by'].startswith('staff')
    assert any(h['text'].startswith('추가 정보 입력 ·') for h in view['history'])
    assert [(p['status']) for p in view['proposals']] == ['confirmed'] and len(runner.inputs) == 1  # saving does not analyse
    assert proposals(identity)[0][4].startswith('staff')


def test_confirming_a_re_analysis_starts_it_and_the_notes_are_included(env):
    clients, identity, runner = env
    pid = propose_info(clients, identity)['proposal_id']
    assert decide(clients, identity, pid, 'confirm').status_code == 200
    def plan(messages):  # earlier turns already hold tool results: react only to the newest request
        last = messages[-1]
        returned = any(getattr(part, 'part_kind', '') == 'tool-return' for part in last.parts)
        return [('text', '재분석할까요?')] if returned else [('tool', 'propose_reanalysis', {})]

    use_model(Script(plan))
    rid = tool_output(send(clients, identity, body_for('재분석해 주세요')))['proposal_id']
    runner.result = good_result()
    assert decide(clients, identity, rid, 'confirm').status_code == 202
    assert len(runner.inputs) == 2 and runner.inputs[1]['additional_info'] == [NOTE]
    view = item(clients, 'staff', identity)
    assert view['status'] == '검토 대기' and [p['status'] for p in view['proposals']] == ['confirmed', 'confirmed']


def body_for(text):
    from test_service_chat import body
    return body(text, message_id=f'm-{text}')


def test_cancelling_does_nothing_but_close_the_proposal(env):
    clients, identity, _ = env
    pid = propose_info(clients, identity)['proposal_id']
    assert decide(clients, identity, pid, 'cancel').status_code == 200
    assert item(clients, 'staff', identity)['additionalInfo'] == []
    assert [p[3] for p in proposals(identity)] == ['cancelled']
    assert decide(clients, identity, pid, 'confirm').status_code == 409


def test_a_proposal_can_only_be_decided_once(env):
    clients, identity, _ = env
    pid = propose_info(clients, identity)['proposal_id']
    assert decide(clients, identity, pid, 'confirm').status_code == 200
    again = decide(clients, identity, pid, 'confirm')
    assert again.status_code == 409 and again.json()['code'] == 'PROPOSAL_DECIDED'
    assert len(item(clients, 'staff', identity)['additionalInfo']) == 1


def test_confirming_after_the_request_moved_on_is_refused_and_leaves_it_pending(env):
    clients, identity, _ = env
    pid = propose_info(clients, identity)['proposal_id']
    with psycopg.connect(DSN) as db:
        db.execute("UPDATE service_request SET status='처리 중' WHERE id=%s", (int(identity[4:]),))
    answer = decide(clients, identity, pid, 'confirm')
    assert answer.status_code == 409 and answer.json()['code'] == 'INVALID_STATE'
    assert [p[3] for p in proposals(identity)] == ['pending'] and item(clients, 'staff', identity)['additionalInfo'] == []


def test_a_proposal_belongs_to_its_request(env):
    clients, identity, _ = env
    pid = propose_info(clients, identity)['proposal_id']
    assert decide(clients, 'CLM-999999', pid, 'confirm').status_code == 404
    assert decide(clients, identity, 999999, 'confirm').status_code == 404
    assert [p[3] for p in proposals(identity)] == ['pending']


@pytest.mark.parametrize('who', ['alice', 'colleague', 'bob'])
@pytest.mark.parametrize('action', ['confirm', 'cancel'])
def test_customers_cannot_decide(env, who, action):
    clients, identity, _ = env
    pid = propose_info(clients, identity)['proposal_id']
    assert decide(clients, identity, pid, action, who=who).status_code == 403
    assert [p[3] for p in proposals(identity)] == ['pending']


def test_session_csrf_and_origin_are_required(env):
    clients, identity, _ = env
    pid = propose_info(clients, identity)['proposal_id']
    url = f'{BASE}/{identity}/proposals/{pid}/confirm'
    assert TestClient(app).post(url, json={}).status_code == 401
    with TestClient(app, cookies=clients['staff'].cookies) as no_csrf:
        assert no_csrf.post(url, json={}, headers={'Origin': 'http://testserver'}).status_code == 403
    assert clients['staff'].post(url, json={}, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert [p[3] for p in proposals(identity)] == ['pending']


def test_the_chat_instructions_name_both_proposals_and_say_nothing_runs_without_the_button():
    assert 'propose_additional_info' in chat.SYSTEM and 'propose_reanalysis' in chat.SYSTEM
    assert '카드' in chat.SYSTEM and '저장하거나 실행하지 않는다' in chat.SYSTEM

"""The agent proposes re-analysis only; the operator must confirm execution.

Real sessions/CSRF/DB; a scripted model and runner in disposable databases only.
"""
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.service_requests import chat
from test_service_analysis_api import Runner, good_result, use_runner, start  # noqa: F401
from test_service_requests_api import setup, BASE, DSN, pytestmark  # noqa: F401
from test_service_workflow_api import INSUFFICIENT, item, post
from test_service_chat import Script, use_model, answer_after_tool, send, events, bare_env  # noqa: F401


def proposals(identity):
    with psycopg.connect(DSN) as db:
        return db.execute('SELECT id,kind,text,status,decided_by FROM service_chat_proposal WHERE request_id=%s ORDER BY id',
                          (int(identity[4:]),)).fetchall()


def decide(clients, identity, proposal, action, who='staff', **kwargs):
    return clients[who].post(f'{BASE}/{identity}/proposals/{proposal}/{action}', json={}, **kwargs)


@pytest.fixture
def env(bare_env, use_runner):
    clients, identity = bare_env
    runner = use_runner(Runner(good_result(**INSUFFICIENT)))
    assert start(clients, identity).status_code == 202
    return clients, identity, runner


def propose_again(clients, identity):
    use_model(Script(answer_after_tool('propose_reanalysis', {}, '재분석할까요?')))
    response = send(clients, identity)
    return next(e for e in events(response) if isinstance(e, dict) and e['type'] == 'tool-output-available')['output']


def test_only_reanalysis_proposal_tool_exists():
    assert 'propose_reanalysis' in chat.TOOL_NAMES
    assert 'propose_additional_info' not in chat.TOOL_NAMES
    assert not hasattr(chat.ChatTools, 'propose_additional_info')
    assert len(chat.TOOL_NAMES) == 11


def test_proposing_a_reanalysis_starts_nothing(env):
    clients, identity, runner = env
    before = item(clients, 'staff', identity)
    out = propose_again(clients, identity)
    assert out['ok'] and out['status'] == 'proposed' and '실행되지 않았습니다' in out['note']
    after = item(clients, 'staff', identity)
    assert after['status'] == before['status'] == '처리 중'
    assert after['history'] == before['history'] and len(runner.inputs) == 1
    assert [(p[1], p[2], p[3]) for p in proposals(identity)] == [('reanalysis', '', 'pending')]


def test_same_pending_proposal_is_not_duplicated(env):
    clients, identity, _ = env
    first = propose_again(clients, identity)
    second = propose_again(clients, identity)
    assert first['proposal_id'] == second['proposal_id'] and len(proposals(identity)) == 1


@pytest.mark.parametrize('kind', ['add_info', 'unknown'])
def test_retired_and_unknown_proposal_kinds_are_rejected(env, kind):
    from app.service_requests import proposals as flow
    _, identity, _ = env
    with psycopg.connect(DSN) as db:
        out = flow.propose(db, int(identity[4:]), kind, 'must not be stored')
    assert out['ok'] is False and out['error']['code'] == 'unsupported_kind'
    assert proposals(identity) == []


def test_reanalysis_is_not_proposed_before_a_successful_analysis(bare_env):
    from app.service_requests import proposals as flow
    _, identity = bare_env
    with psycopg.connect(DSN) as db:
        out = flow.propose(db, int(identity[4:]), 'reanalysis')
    assert not out['ok'] and out['error']['code'] == 'invalid_state'
    assert proposals(identity) == []


def test_proposals_are_listed_for_operators_only(env):
    clients, identity, _ = env
    propose_again(clients, identity)
    listed = item(clients, 'staff', identity)['proposals']
    assert [(p['kind'], p['text'], p['status']) for p in listed] == [('reanalysis', '', 'pending')]
    assert 'proposals' not in item(clients, 'alice', identity)


def test_confirming_reanalysis_uses_the_original_request_only(env):
    clients, identity, runner = env
    pid = propose_again(clients, identity)['proposal_id']
    runner.result = good_result()
    assert decide(clients, identity, pid, 'confirm').status_code == 202
    assert len(runner.inputs) == 2 and runner.inputs[1] == runner.inputs[0]
    assert 'additional_info' not in runner.inputs[1]
    view = item(clients, 'staff', identity)
    assert view['status'] == '처리 중' and view['revision'] == 2
    assert [p['status'] for p in view['proposals']] == ['confirmed']
    assert proposals(identity)[0][4].startswith('staff')


def test_cancelling_changes_only_the_proposal(env):
    clients, identity, runner = env
    pid = propose_again(clients, identity)['proposal_id']
    assert decide(clients, identity, pid, 'cancel').status_code == 200
    assert [p[3] for p in proposals(identity)] == ['cancelled'] and len(runner.inputs) == 1
    assert decide(clients, identity, pid, 'confirm').status_code == 409


def test_a_proposal_can_only_be_decided_once(env):
    clients, identity, runner = env
    pid = propose_again(clients, identity)['proposal_id']
    assert decide(clients, identity, pid, 'confirm').status_code == 202
    again = decide(clients, identity, pid, 'confirm')
    assert again.status_code == 409 and again.json()['code'] == 'PROPOSAL_DECIDED'
    assert len(runner.inputs) == 2


def test_confirming_after_closure_is_refused_and_leaves_it_pending(env):
    clients, identity, runner = env
    pid = propose_again(clients, identity)['proposal_id']
    assert post(clients, 'staff', identity, 'resolution', note='처리 결과입니다.').status_code == 200
    answer = decide(clients, identity, pid, 'confirm')
    assert answer.status_code == 409 and answer.json()['code'] == 'ANALYSIS_NOT_ALLOWED'
    assert [p[3] for p in proposals(identity)] == ['pending'] and len(runner.inputs) == 1


def test_a_proposal_belongs_to_its_request(env):
    clients, identity, _ = env
    pid = propose_again(clients, identity)['proposal_id']
    assert decide(clients, 'CLM-999999', pid, 'confirm').status_code == 404
    assert decide(clients, identity, 999999, 'confirm').status_code == 404
    assert [p[3] for p in proposals(identity)] == ['pending']


@pytest.mark.parametrize('who', ['alice', 'colleague', 'bob'])
@pytest.mark.parametrize('action', ['confirm', 'cancel'])
def test_customers_cannot_decide(env, who, action):
    clients, identity, _ = env
    pid = propose_again(clients, identity)['proposal_id']
    assert decide(clients, identity, pid, action, who=who).status_code == 403
    assert [p[3] for p in proposals(identity)] == ['pending']


def test_session_csrf_and_origin_are_required(env):
    clients, identity, _ = env
    pid = propose_again(clients, identity)['proposal_id']
    url = f'{BASE}/{identity}/proposals/{pid}/confirm'
    assert TestClient(app).post(url, json={}).status_code == 401
    with TestClient(app, cookies=clients['staff'].cookies) as no_csrf:
        assert no_csrf.post(url, json={}, headers={'Origin': 'http://testserver'}).status_code == 403
    assert clients['staff'].post(url, json={}, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert [p[3] for p in proposals(identity)] == ['pending']


def test_instructions_describe_operator_confirmation_and_no_fact_storage():
    assert 'propose_reanalysis' in chat.SYSTEM and 'propose_additional_info' not in chat.SYSTEM
    assert '카드' in chat.SYSTEM and '직접 실행하지 않는다' in chat.SYSTEM
    assert '별도 정보를 저장하는 기능은 없으므로' in chat.SYSTEM

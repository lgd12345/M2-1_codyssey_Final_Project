"""Operators add what they learned outside the app; re-analysis receives it. Customers are never asked anything.

Real sessions/CSRF/authorization/DB; only the model runner is a controlled double.
Run ONLY through scripts/test_isolated.py (disposable DB).
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from test_service_analysis_api import Runner, good_result, use_runner, submit, start  # noqa: F401
from test_service_requests_api import setup, BASE, pytestmark  # noqa: F401
from test_service_workflow_api import INSUFFICIENT, approved, item, post, reviewed  # noqa: F401

CALL_NOTE = '현장 확인 결과 알람 2023이 스핀들 정지 직후에 발생함. 고객 통화로 확인.'


def add_info(clients, identity, text=CALL_NOTE, who='staff'):
    return clients[who].post(f'{BASE}/{identity}/additional-info', json={'text': text})


def test_operator_adds_information_with_author_time_and_an_internal_history_entry(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner(good_result(**INSUFFICIENT)))
    identity = reviewed(clients, equipment)
    response = add_info(clients, identity)
    assert response.status_code == 201
    view = response.json()
    assert [note['text'] for note in view['additionalInfo']] == [CALL_NOTE]
    author = view['additionalInfo'][0]['by']
    assert author.startswith('staff')  # the logged-in operator, never a value sent by the browser
    assert view['additionalInfo'][0]['at'] and view['additionalInfo'][0]['id']
    assert any(entry['text'] == f'추가 정보 입력 · {author}' for entry in view['history'])
    with TestClient(app, cookies=clients['staff'].cookies) as fresh:  # durable, not process-local
        assert fresh.get(f'{BASE}/{identity}').json()['additionalInfo'] == view['additionalInfo']


def test_notes_are_kept_in_entry_order(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner(good_result(**INSUFFICIENT)))
    identity = reviewed(clients, equipment)
    for text in ('첫 번째 확인', '두 번째 확인'):
        assert add_info(clients, identity, text).status_code == 201
    assert [note['text'] for note in item(clients, 'staff', identity)['additionalInfo']] == ['첫 번째 확인', '두 번째 확인']


def test_reanalysis_input_contains_the_notes_but_the_first_analysis_has_none(setup, use_runner):
    clients, equipment = setup
    runner = use_runner(Runner(good_result(**INSUFFICIENT)))
    identity = reviewed(clients, equipment)
    assert runner.inputs[0]['additional_info'] == []
    assert add_info(clients, identity).status_code == 201
    runner.result = good_result()
    assert post(clients, 'staff', identity, 'reanalysis').status_code == 202
    assert runner.inputs[1]['additional_info'] == [CALL_NOTE]
    assert 'contact' not in runner.inputs[1]
    after = item(clients, 'staff', identity)
    assert after['status'] == '검토 대기' and after['additionalInfo'][0]['text'] == CALL_NOTE


def test_adding_information_does_not_start_an_analysis_by_itself(setup, use_runner):
    clients, equipment = setup
    runner = use_runner(Runner(good_result(**INSUFFICIENT)))
    identity = reviewed(clients, equipment)
    assert add_info(clients, identity).status_code == 201
    assert len(runner.inputs) == 1 and item(clients, 'staff', identity)['status'] == '추가 정보 필요'


@pytest.mark.parametrize('who, expected', [('alice', 403), ('colleague', 403), ('bob', 403)])
def test_customers_cannot_add_information(setup, use_runner, who, expected):
    clients, equipment = setup
    use_runner(Runner(good_result(**INSUFFICIENT)))
    identity = reviewed(clients, equipment)
    assert add_info(clients, identity, who=who).status_code == expected
    assert item(clients, 'staff', identity)['additionalInfo'] == []


def test_session_csrf_and_origin_are_required(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner(good_result(**INSUFFICIENT)))
    identity = reviewed(clients, equipment)
    url = f'{BASE}/{identity}/additional-info'
    assert TestClient(app).post(url, json={'text': CALL_NOTE}).status_code == 401
    with TestClient(app, cookies=clients['staff'].cookies) as no_csrf:
        assert no_csrf.post(url, json={'text': CALL_NOTE}, headers={'Origin': 'http://testserver'}).status_code == 403
    assert clients['staff'].post(url, json={'text': CALL_NOTE}, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert item(clients, 'staff', identity)['additionalInfo'] == []


@pytest.mark.parametrize('payload', [{}, {'text': ''}, {'text': '   '}, {'text': 'x' * 2001},
                                      {'text': 'ok', 'by': 'forged'}, {'text': 5}])
def test_invalid_notes_are_rejected(setup, use_runner, payload):
    clients, equipment = setup
    use_runner(Runner(good_result(**INSUFFICIENT)))
    identity = reviewed(clients, equipment)
    assert clients['staff'].post(f'{BASE}/{identity}/additional-info', json=payload).status_code == 422
    assert item(clients, 'staff', identity)['additionalInfo'] == []


def test_information_can_only_be_added_while_the_request_can_be_re_analysed(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    received = submit(clients, equipment)
    assert add_info(clients, received).status_code == 409
    identity = approved(clients, equipment)  # being processed: analysis is final
    response = add_info(clients, identity)
    assert response.status_code == 409 and response.json()['code'] == 'INVALID_STATE'
    assert item(clients, 'staff', identity)['additionalInfo'] == []
    declined = reviewed(clients, equipment)
    assert post(clients, 'staff', declined, 'decline', reason='사유').status_code == 200
    assert add_info(clients, declined).status_code == 201  # a declined request may be analysed again


def test_unknown_request_is_not_found(setup):
    clients, _ = setup
    assert add_info(clients, 'CLM-999999').status_code == 404


def test_customers_never_see_the_notes_the_questions_or_a_request_for_information(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner(good_result(**INSUFFICIENT)))
    identity = reviewed(clients, equipment)
    assert add_info(clients, identity).status_code == 201
    for who in ('alice', 'colleague'):
        view = item(clients, who, identity)
        assert view['status'] == '확인 중'  # nothing is asked of the customer
        text = str(view)
        assert CALL_NOTE not in text and '알람 번호는?' not in text and 'additionalInfo' not in view
        assert all('추가 정보' not in entry['text'] for entry in view['history'])

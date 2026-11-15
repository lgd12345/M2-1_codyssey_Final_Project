"""The mail window opens from a fixed template (no AI call); `AI로 작성` fills it through the agent. Neither saves or sends.

Real sessions/CSRF/DB; the model is a scripted double. Run ONLY through scripts/test_isolated.py (disposable DB).
"""
import json
from contextlib import asynccontextmanager

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from app.main import app
from app.service_requests import chat
from test_service_analysis_api import Runner, good_result, use_runner, start  # noqa: F401
from test_service_requests_api import setup, BASE, DSN, pytestmark  # noqa: F401
from test_service_workflow_api import item, reviewed  # noqa: F401
from test_service_chat import DUMMY_SETTINGS
from test_mail_drafts import DEV


def template(clients, identity, key='service', who='staff'):
    return clients[who].get(f'{BASE}/{identity}/mail-template', params={'department_key': key})


def ai(clients, identity, key='service', who='staff', **extra):
    return clients[who].post(f'{BASE}/{identity}/mail-template/ai', json={'department_key': key, **extra})


def draft_count(identity):
    with psycopg.connect(DSN) as db:
        return db.execute('SELECT count(*) FROM service_mail_draft WHERE request_id=%s', (int(identity[4:]),)).fetchone()[0]


@pytest.fixture
def analysed(setup, use_runner, recorded_mail):
    clients, equipment = setup
    use_runner(Runner(good_result()))
    identity = reviewed(clients, equipment)
    yield clients, identity, recorded_mail
    with psycopg.connect(DSN) as db:
        db.execute("UPDATE service_department SET recipients=ARRAY[%s], active=TRUE", (DEV,))
    app.dependency_overrides.pop(chat.get_chat_runtime, None)


def model_returning(subject, body):
    seen = []

    def function(messages, info):
        seen.append((messages, info))
        assert info.output_tools, 'the mail agent must answer with a structured subject and body'
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {'subject': subject, 'body': body})])

    @asynccontextmanager
    async def provide():
        yield FunctionModel(function)

    app.dependency_overrides[chat.get_chat_runtime] = lambda: chat.ChatRuntime(provide, DUMMY_SETTINGS)
    return seen


# ---------- the template ----------

@pytest.mark.parametrize('key, subject_start, phrase', [
    ('service', '[출동 요청]', '출동 점검을 요청'), ('quality', '[품질 보고]', '보고'),
    ('parts', '[부품 수배 요청]', '부품 수배'), ('sales', '[영업 안내 요청]', '보증·비용 안내')])
def test_each_department_gets_a_fixed_template_filled_from_the_request(analysed, key, subject_start, phrase):
    clients, identity, mail = analysed
    answer = template(clients, identity, key)
    assert answer.status_code == 200
    data = answer.json()
    assert data['subject'].startswith(subject_start) and identity in data['subject'] and 'F400' in data['subject']
    for expected in (phrase, f'요청 번호: {identity}', '기종: F400', '접수 사유: 공구 교환 이상', 'ATC 교환 중 멈춥니다.'):
        assert expected in data['body']
    assert data['departmentName'] and data['recipients'] == [DEV]  # the operator sees who will receive it
    assert '\n' not in data['subject'] and len(data['subject']) <= 150
    assert mail.messages == [] and draft_count(identity) == 0  # opening the window saves and sends nothing


def test_the_template_carries_the_analysis_causes_and_case_numbers_but_never_a_worker_id_or_an_address(analysed):
    clients, identity, _ = analysed
    data = template(clients, identity).json()
    assert 'ATC 암 구동 불량 (가능성 높음)' in data['body'] and 'FSR-00001' in data['body']
    assert 'EMP-' not in data['body'] and '@' not in data['body'] and DEV not in data['subject'] + data['body']


def test_without_an_analysis_the_template_still_opens_with_the_request_facts_only(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    from test_service_analysis_api import submit
    identity = submit(clients, equipment)
    data = template(clients, identity).json()
    assert 'ATC 교환 중 멈춥니다.' in data['body'] and '원인 후보' not in data['body'] and '참고 FSR' not in data['body']


def test_a_customer_message_cannot_smuggle_a_worker_id_into_the_template(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    from test_service_requests_api import body
    from test_service_analysis_api import submit  # noqa: F401
    payload = {**body(equipment[0]), 'message': '담당 EMP-0031 님께 확인했습니다. ATC 정지'}
    identity = clients['alice'].post(BASE, json=payload).json()['id']
    text = template(clients, identity).json()['body']
    assert 'EMP-0031' not in text and 'ATC 정지' in text


def test_the_template_is_refused_for_unknown_inactive_or_addressless_departments(analysed):
    clients, identity, _ = analysed
    assert template(clients, identity, 'legal').status_code == 422
    with psycopg.connect(DSN) as db:
        db.execute("UPDATE service_department SET active=FALSE WHERE key='sales'")
        db.execute("UPDATE service_department SET recipients='{}' WHERE key='parts'")
    assert template(clients, identity, 'sales').status_code == 422
    assert template(clients, identity, 'parts').status_code == 422
    assert template(clients, 'CLM-999999').status_code == 404


@pytest.mark.parametrize('who', ['alice', 'colleague', 'bob'])
def test_customers_cannot_open_the_template_or_use_ai_compose(analysed, who):
    clients, identity, _ = analysed
    assert template(clients, identity, who=who).status_code == 403
    assert ai(clients, identity, who=who).status_code == 403


# ---------- AI compose ----------

def test_ai_compose_returns_a_suggestion_that_is_not_saved_or_sent(analysed):
    clients, identity, mail = analysed
    seen = model_returning('[출동 요청] ATC 정지 점검 부탁드립니다', 'F400 ATC 정지 건입니다. 현장 점검을 요청드립니다.')
    answer = ai(clients, identity)
    assert answer.status_code == 200
    assert answer.json() == {'subject': '[출동 요청] ATC 정지 점검 부탁드립니다',
                             'body': 'F400 ATC 정지 건입니다. 현장 점검을 요청드립니다.'}
    assert mail.messages == [] and draft_count(identity) == 0
    context = str(seen[0][1].instructions) + str(seen[0][0])
    assert 'ATC 교환 중 멈춥니다.' in context and '서비스' in context and '신뢰할 수 없는' in context
    assert DEV not in context and '@' not in context  # the model never sees an address


def test_the_agent_may_be_given_a_short_instruction_for_the_draft(analysed):
    clients, identity, _ = analysed
    seen = model_returning('제목', '본문')
    assert ai(clients, identity, instruction='긴급 건임을 강조해 주세요').status_code == 200
    assert '긴급 건임을 강조해 주세요' in str(seen[0][0])
    assert ai(clients, identity, instruction='x' * 501).status_code == 422


@pytest.mark.parametrize('subject, body', [('제목', '담당 작업자는 EMP-0003 입니다'), ('줄\n바꿈', '본문'), ('', '본문'), ('제목', '')])
def test_an_ai_draft_that_breaks_the_mail_rules_is_refused_not_passed_on(analysed, subject, body):
    clients, identity, _ = analysed
    model_returning(subject, body)
    answer = ai(clients, identity)
    assert answer.status_code == 502 and answer.json()['code'] == 'MAIL_AI_INVALID' and 'EMP-0003' not in answer.text


def test_a_model_failure_is_reported_with_a_fixed_sentence(analysed):
    clients, identity, _ = analysed

    @asynccontextmanager
    async def broken():
        raise RuntimeError('secret-key abcdef leaked')
        yield

    app.dependency_overrides[chat.get_chat_runtime] = lambda: chat.ChatRuntime(broken, DUMMY_SETTINGS)
    answer = ai(clients, identity)
    assert answer.status_code == 502 and 'abcdef' not in answer.text and 'secret-key' not in answer.text


def test_ai_compose_needs_csrf_and_a_valid_department(analysed):
    clients, identity, _ = analysed
    model_returning('제목', '본문')
    url = f'{BASE}/{identity}/mail-template/ai'
    assert TestClient(app).post(url, json={'department_key': 'service'}).status_code == 401
    with TestClient(app, cookies=clients['staff'].cookies) as no_csrf:
        assert no_csrf.post(url, json={'department_key': 'service'}, headers={'Origin': 'http://testserver'}).status_code == 403
    assert ai(clients, identity, 'legal').status_code == 422


def test_the_chat_instructions_forbid_markdown_and_require_the_draft_tool():
    assert '마크다운' in chat.SYSTEM and 'draft_department_mail를 호출' in chat.SYSTEM

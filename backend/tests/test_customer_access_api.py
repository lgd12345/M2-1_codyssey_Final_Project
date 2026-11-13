import asyncio
from contextlib import contextmanager
from unittest.mock import AsyncMock, Mock
from uuid import UUID

from fastapi.testclient import TestClient
import psycopg
import pytest

from app.auth.deps import require_csrf, require_user
from app.auth.service import AuthUser, LoginRequired, SessionInfo
from app.customer_access import routes
from customer_access_fakes import service

ORIGIN = {'Origin':'https://testserver'}
START = {'purpose':'guest','company_code':'DEMO','email':'contact@example.org','consent':True,'policy_version':'synthetic-v1'}


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr('dotenv.load_dotenv',lambda *_a,**_k:False)
    monkeypatch.delenv('CUSTOMER_ACCESS_ENABLED',raising=False)
    connector=Mock(side_effect=AssertionError('No actual database allowed in route tests'))
    monkeypatch.setattr(psycopg,'connect',connector)
    from app.main import app
    monkeypatch.setattr(app,'dependency_overrides',{})
    yield app
    connector.assert_not_called()


@pytest.fixture
def client(app):
    with TestClient(app,base_url='https://testserver') as client:yield client


@pytest.fixture
def enabled(app,monkeypatch):
    value=service();outbox=[]
    app.dependency_overrides[routes.configured_service]=lambda:value
    async def deliver(s,identity,recipient,code):
        outbox.append((recipient,code));s.sent(identity,True)
    monkeypatch.setattr(routes,'deliver',deliver)
    return value,outbox


def test_disabled_status_and_posts_do_not_touch_database_or_mail(app,client,monkeypatch):
    sender=Mock(side_effect=AssertionError('No mail when disabled'))
    monkeypatch.setattr(routes,'deliver',sender)
    assert client.get('/api/v1/access/status').json()=={'available':False,'registration_available':False,'policy':None}
    response=client.post('/api/v1/access/challenges',json=START,headers=ORIGIN)
    assert response.status_code==503
    sender.assert_not_called()
    assert client.get('/api/health').json()=={'status':'ok'}


def test_challenge_response_never_includes_code_or_destination_and_cookie_is_scoped(client,enabled):
    _,outbox=enabled
    response=client.post('/api/v1/access/challenges',json=START,headers=ORIGIN)
    assert response.status_code==202 and len(outbox)==1
    assert outbox[0][1] not in response.text and START['email'] not in response.text
    cookie=response.headers['set-cookie'].lower()
    for flag in ['secure','httponly','samesite=strict','path=/api/v1/access']:assert flag in cookie
    assert 'no-store' in response.headers['cache-control']


def test_unknown_contact_has_explicit_input_error_without_sending_or_exposing_registered_email(client,enabled):
    value,outbox=enabled
    response=client.post('/api/v1/access/challenges',json={**START,'email':'unknown@example.org'},headers=ORIGIN)
    assert response.status_code==400 and not outbox
    assert response.json()['code']=='COMPANY_EMAIL_MISMATCH'
    assert '이메일을 확인해 주세요' in response.json()['detail']
    assert START['email'] not in response.text and 'set-cookie' not in response.headers
    assert len(value.repository.challenges)==1


def test_invalid_company_has_explicit_error_and_never_schedules_mail(client,enabled):
    value,outbox=enabled
    response=client.post('/api/v1/access/challenges',json={**START,'company_code':'UNKNOWN'},headers=ORIGIN)
    assert response.status_code==400 and response.json()['code']=='COMPANY_NOT_FOUND'
    assert '등록되지 않은 회사코드' in response.json()['detail']
    assert not outbox and 'set-cookie' not in response.headers
    assert len(value.repository.challenges)==1
    assert 'no-store' in response.headers['cache-control']




def test_existing_customer_is_disclosed_only_after_email_verification_and_gets_no_login_session(client,enabled):
    value,outbox=enabled
    original={'id':UUID(int=77),'contact':UUID(int=1),'role':'customer','password_hash':'synthetic-original'}
    value.repository.users['existing-customer']=original.copy()
    start=client.post('/api/v1/access/challenges',json={**START,'purpose':'register'},headers=ORIGIN)
    assert start.status_code==202 and 'already_registered' not in start.text
    payload={'code':'wrong','consent':True,'policy_version':'synthetic-v1'}
    assert client.post('/api/v1/access/registration/verify',json=payload,headers=ORIGIN).json()['code']=='ACCESS_CODE_INVALID'
    payload['code']=outbox[-1][1]
    verified=client.post('/api/v1/access/registration/verify',json=payload,headers=ORIGIN)
    assert verified.status_code==200 and verified.json()=={'state':'already_registered'}
    assert 'manual_session' not in client.cookies and 'claim_register_challenge' not in client.cookies
    assert value.repository.users=={'existing-customer':original}


@pytest.mark.parametrize('origin',[{}, {'Origin':'https://evil.example.org'}])
def test_email_verification_requires_same_origin(client,enabled,origin):
    assert client.post('/api/v1/access/registration/verify',json={'code':'123456','consent':True,'policy_version':'synthetic-v1'},headers=origin).status_code==403


@pytest.mark.parametrize('extra',[{'login_id':'operator-demo'},{'email':'other@example.org'},{'role':'admin'}])
def test_public_registration_cannot_choose_identity_or_role(client,enabled,extra):
    response=client.post('/api/v1/access/registration',json={'code':'123456','password':'synthetic-password-123','consent':True,'policy_version':'synthetic-v1',**extra},headers=ORIGIN)
    assert response.status_code==422 and not enabled[0].repository.users


def test_email_registration_flow_returns_verified_identity_and_no_operator_session(client,enabled):
    value,outbox=enabled
    client.post('/api/v1/access/challenges',json={**START,'purpose':'register'},headers=ORIGIN)
    payload={'code':outbox[-1][1],'consent':True,'policy_version':'synthetic-v1'}
    verified=client.post('/api/v1/access/registration/verify',json=payload,headers=ORIGIN)
    assert verified.status_code==200 and verified.json()=={'state':'verified','email':START['email']}
    result=client.post('/api/v1/access/registration',json={**payload,'password':'synthetic-password-123'},headers=ORIGIN)
    assert result.status_code==201 and value.repository.users[START['email']]['role']=='customer'
    assert 'manual_session' not in client.cookies






@pytest.mark.parametrize('origin',[{}, {'Origin':'https://evil.example.org'}])
def test_issuance_rejects_missing_and_foreign_origin(client,enabled,origin):
    assert client.post('/api/v1/access/challenges',json=START,headers=origin).status_code==403
    assert not enabled[1]


@pytest.mark.parametrize('extra',[{'role':'admin'},{'company_id':'another-company'},{'is_active':True}])
def test_role_and_company_id_injection_is_rejected_without_mail(client,enabled,extra):
    response=client.post('/api/v1/access/challenges',json={**START,**extra},headers=ORIGIN)
    assert response.status_code==422 and not enabled[1]
    assert 'input' not in response.json()


def test_password_validation_does_not_echo_submitted_password(client,enabled):
    response=client.post('/api/v1/access/registration',json={'code':'123456','login_id':'demo','password':'sensitive-short',
        'consent':True,'policy_version':'synthetic-v1','role':'admin'},headers=ORIGIN)
    assert response.status_code==422 and 'sensitive-short' not in response.text


def test_oversized_json_is_rejected_before_parsing_or_service(client,enabled):
    response=client.post('/api/v1/access/challenges',content=b'x'*32769,headers={**ORIGIN,'Content-Type':'application/json'})
    assert response.status_code==413 and not enabled[1]


def test_full_guest_cookie_flow_and_replay_protection(client,enabled):
    _,outbox=enabled
    client.post('/api/v1/access/challenges',json=START,headers=ORIGIN)
    verified=client.post('/api/v1/access/guest/session',json={'code':outbox[-1][1],'consent':True,'policy_version':'synthetic-v1'},headers=ORIGIN)
    assert verified.status_code==200
    csrf=verified.json()['csrf_token']
    assert client.get('/api/v1/access/guest/session').json()['authenticated']
    payload=dict(title='합성 문의',body='<script>test-only</script>',consent=True,policy_version='synthetic-v1')
    assert client.post('/api/v1/access/guest/inquiry',json=payload,headers=ORIGIN).status_code==403
    stored=client.post('/api/v1/access/guest/inquiry',json=payload,headers={**ORIGIN,'X-CSRF-Token':csrf})
    assert stored.status_code==201
    assert client.get('/api/v1/access/guest/inquiry').json()==stored.json()
    # A different browser does not possess this inquiry session.
    with TestClient(client.app,base_url='https://testserver') as other:
        assert other.get('/api/v1/access/guest/inquiry').status_code==401


def test_public_registration_is_customer_only_and_does_not_create_operator_cookie(client,enabled):
    value,outbox=enabled
    client.post('/api/v1/access/challenges',json={**START,'purpose':'register'},headers=ORIGIN)
    response=client.post('/api/v1/access/registration',json={'code':outbox[-1][1],'consent':True,'policy_version':'synthetic-v1',
        'password':'synthetic-password-123'},headers=ORIGIN)
    assert response.status_code==201 and response.json()['state']=='registered'
    assert value.repository.users['contact@example.org']['role']=='customer'
    assert 'manual_session' not in client.cookies


def set_role(app,role):
    session=SessionInfo(AuthUser(UUID(int=25),'synthetic-account',role),'synthetic-csrf')
    app.dependency_overrides[require_user]=lambda:session
    app.dependency_overrides[require_csrf]=lambda:session


@pytest.mark.parametrize('path,method', [('/api/v1/documents','GET'),('/api/v1/agent/runs','GET'),
    ('/api/v1/agent/runs/00000000-0000-0000-0000-000000000001','GET'),
    ('/api/v1/agent/runs/00000000-0000-0000-0000-000000000001/assets/a','GET'),
    ('/api/v1/agent/runs','POST'),('/api/v1/agent/stream','POST'),('/api/v1/admin/db-inspection','GET')])
def test_customer_cannot_call_any_operator_or_system_endpoint(app,client,path,method):
    set_role(app,'customer')
    response=client.request(method,path,json={'question':'합성 질문'} if method=='POST' else None)
    assert response.status_code==403


@pytest.mark.parametrize('role',['admin','user'])
def test_manually_issued_operator_accounts_still_access_manual_documents(app,client,monkeypatch,role):
    set_role(app,role)
    from app.documents import routes as document_routes
    connection=Mock();connection.execute.return_value.fetchall.return_value=[];connection.execute.return_value.fetchone.return_value=(False,)
    @contextmanager
    def database():yield connection
    monkeypatch.setattr(document_routes,'database',database)
    assert client.get('/api/v1/documents').status_code==200


def test_guest_cookie_does_not_authenticate_as_customer_or_operator(app,client,enabled):
    def anonymous():raise LoginRequired()
    app.dependency_overrides[require_user]=anonymous
    client.cookies.set('claim_guest_session','synthetic-token')
    assert client.get('/api/v1/documents').status_code==401
    assert client.get('/api/v1/access/customer/profile').status_code==401


def test_profile_uses_authenticated_identity_and_cannot_be_switched_by_query(app,client,enabled):
    value,_=enabled
    value.repository.users['customer']={'id':UUID(int=25),'contact':UUID(int=1),'role':'customer'}
    set_role(app,'customer')
    response=client.get('/api/v1/access/customer/profile?company_id=another-company&user_id=other')
    assert response.status_code==200 and response.json()['company']['id']==str(UUID(int=10))


def test_smtp_uses_verified_tls_and_does_not_retry(monkeypatch, capsys, caplog):
    from app.customer_access.mailer import send_code,deliver
    import aiosmtplib
    value=service();sender=AsyncMock(return_value=({},'ok'))
    monkeypatch.setattr(aiosmtplib,'send',sender)
    asyncio.run(send_code(value.settings,'contact@example.org','123456'))
    kwargs=sender.call_args.kwargs
    assert kwargs['use_tls'] and kwargs['validate_certs'] and kwargs['start_tls'] is False
    assert kwargs['hostname']=='smtp.gmail.com' and kwargs['port']==465 and kwargs['timeout']==10
    assert kwargs['username']==value.settings.smtp_username=='sender@example.org'
    assert kwargs['password']==value.settings.smtp_password
    message=sender.call_args.args[0]
    assert message['From']=='sender@example.org' and message['To']=='contact@example.org'
    assert '123456' in message.get_content() and message['Resend-Idempotency-Key'] is None
    sender.assert_awaited_once()
    sender.reset_mock();sender.side_effect=RuntimeError('synthetic SMTP secret; must not be logged')
    value.sent=Mock()
    asyncio.run(deliver(value,UUID(int=22),'contact@example.org','123456'))
    sender.assert_awaited_once();value.sent.assert_called_once_with(UUID(int=22),False)
    captured=capsys.readouterr()
    assert not captured.out and not captured.err and not caplog.text


def test_successful_smtp_submission_marks_challenge_sent_once(monkeypatch):
    from app.customer_access.mailer import deliver
    import aiosmtplib
    value=service();value.sent=Mock()
    sender=AsyncMock(return_value=({},'accepted'))
    monkeypatch.setattr(aiosmtplib,'send',sender)
    asyncio.run(deliver(value,UUID(int=22),'contact@example.org','123456'))
    sender.assert_awaited_once();value.sent.assert_called_once_with(UUID(int=22),True)

"""Authorization, expiry, CSRF, input and UI checks; no real DB/mail."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib
import json
from unittest.mock import Mock
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import psycopg
import pytest

from app.auth import deps
from app.auth.service import AuthUser,SessionInfo
from app.company_admin import install_core as core,install_routes as routes
from app.company_admin.routes import router as company_router
from app.customer_access.limits import AccessBodyLimit

PATH='/api/v1/companies/installation'
APPROVAL='synthetic-approval-code-with-no-actual-access-123456789'
SESSION=SessionInfo(AuthUser(UUID(int=1),'synthetic-operator','user'),'synthetic-csrf')
HEADERS={'Origin':'https://testserver','X-CSRF-Token':'synthetic-csrf'}


def grant_for(session=SESSION):
    now=datetime.now(timezone.utc)
    return {'version':1,'action':core.ACTION,'release_id':'a'*32,
        'subject_sha256':core.subject_hash(session),'approval_sha256':hashlib.sha256(APPROVAL.encode()).hexdigest(),
        'issued_at':(now-timedelta(seconds=1)).isoformat(),'expires_at':(now+timedelta(minutes=30)).isoformat(),
        'origin':'https://testserver','migration_checksums':core.checksums()}


@pytest.fixture
def fixture(monkeypatch,tmp_path):
    connector=Mock(side_effect=AssertionError('No real database in route tests'))
    monkeypatch.setattr(psycopg,'connect',connector)
    manifest=tmp_path/'installation-grant.json'
    grant=grant_for();manifest.write_text(json.dumps(grant),encoding='utf-8')
    monkeypatch.setattr(core,'GRANT_FILE',manifest)
    monkeypatch.setenv('DATABASE_URL','synthetic-dsn-do-not-connect')
    monkeypatch.delenv('RAG_DATABASE_URL',raising=False)
    identity={'session':SESSION}
    monkeypatch.setattr(deps,'current_session',lambda request:identity['session'])
    status=Mock(return_value={'state':'ready','target_fingerprint':'b'*64,'release_id':grant['release_id'],
                             'expires_at':grant['expires_at'],'versions':['001','004']})
    apply=Mock(return_value={'state':'installed','schema_created':True,'existing_accounts_changed':False,'mail_sent':False})
    monkeypatch.setattr(core,'inspect_installation',status)
    monkeypatch.setattr(core,'apply_installation',apply)
    app=FastAPI();app.add_middleware(AccessBodyLimit,prefix='/api/v1/companies',methods=('POST','PUT'))
    app.include_router(routes.router);app.include_router(company_router)
    with TestClient(app,base_url='https://testserver') as client:
        yield client,identity,manifest,grant,status,apply
    connector.assert_not_called()


def payload(**overrides):
    return dict(dict(approval_code=APPROVAL,target_fingerprint='b'*64,release_id='a'*32,confirmed=True),**overrides)


@pytest.mark.parametrize('role,status',[(None,401),('customer',403),('unexpected',403)])
def test_all_install_routes_require_operator_before_any_inspection(fixture,role,status):
    client,identity,_,_,reader,writer=fixture
    identity['session']=None if role is None else SessionInfo(AuthUser(UUID(int=1),'synthetic',role),'synthetic-csrf')
    for path in (PATH,PATH+'/status'):
        assert client.get(path).status_code==status
    assert client.post(PATH+'/apply',json=payload(),headers=HEADERS).status_code==status
    reader.assert_not_called();writer.assert_not_called()


@pytest.mark.parametrize('case',['missing','expired','future','too_long','wrong_subject','wrong_hashes','wrong_origin','unknown_field','wrong_action','bad_json'])
def test_invalid_deployment_grants_fail_before_database(fixture,case):
    client,_,manifest,grant,reader,writer=fixture
    changed=deepcopy(grant)
    now=datetime.now(timezone.utc)
    if case=='missing':manifest.unlink()
    elif case=='bad_json':manifest.write_text('{',encoding='utf-8')
    else:
        if case=='expired':changed['expires_at']=(now-timedelta(minutes=1)).isoformat()
        if case=='future':changed['issued_at']=(now+timedelta(minutes=5)).isoformat()
        if case=='too_long':changed['expires_at']=(now+timedelta(hours=2)).isoformat()
        if case=='wrong_subject':changed['subject_sha256']='0'*64
        if case=='wrong_hashes':changed['migration_checksums']['004']='0'*64
        if case=='wrong_origin':changed['origin']='https://other.invalid'
        if case=='unknown_field':changed['sql']='never permitted'
        if case=='wrong_action':changed['action']='arbitrary_action'
        manifest.write_text(json.dumps(changed),encoding='utf-8')
    for path in (PATH,PATH+'/status'):
        response=client.get(path)
        assert response.status_code==403 and APPROVAL not in response.text
    assert client.post(PATH+'/apply',json=payload(),headers=HEADERS).status_code==403
    reader.assert_not_called();writer.assert_not_called()


@pytest.mark.parametrize('headers',[{}, {'Origin':'https://testserver'},
    {'Origin':'https://other.invalid','X-CSRF-Token':'synthetic-csrf'},
    {'Origin':'http://testserver','X-CSRF-Token':'synthetic-csrf'},
    {'Origin':'https://testserver','X-CSRF-Token':'wrong'}])
def test_write_requires_exact_origin_and_csrf(fixture,headers):
    client,_,_,_,_,writer=fixture
    assert client.post(PATH+'/apply',json=payload(),headers=headers).status_code==403
    writer.assert_not_called()


@pytest.mark.parametrize('changes',[{'approval_code':'x'*43},{'release_id':'c'*32},{'confirmed':False}])
def test_wrong_confirmation_or_code_never_applies(fixture,changes):
    client,_,_,_,_,writer=fixture
    response=client.post(PATH+'/apply',json=payload(**changes),headers=HEADERS)
    assert response.status_code==403 and APPROVAL not in response.text
    writer.assert_not_called()


@pytest.mark.parametrize('changes',[{'sql':'DROP TABLE anything'},{'dsn':'postgresql://not-allowed'},
    {'confirmed':'true'},{'approval_code':'short'},{'target_fingerprint':'invalid'}])
def test_no_input_sql_dsn_or_reflected_secret(fixture,changes):
    client,_,_,_,_,writer=fixture
    response=client.post(PATH+'/apply',json=payload(**changes),headers=HEADERS)
    assert response.status_code==422 and APPROVAL not in response.text
    writer.assert_not_called()


def test_page_status_apply_and_private_headers(fixture):
    client,_,_,_,reader,writer=fixture
    page=client.get(PATH)
    assert page.status_code==200 and '고객사 관리 데이터 준비' in page.text
    assert APPROVAL not in page.text and 'synthetic-csrf' not in page.text
    assert "frame-ancestors 'none'" in page.headers['content-security-policy']
    assert "'sha256-" in page.headers['content-security-policy']
    assert page.headers['referrer-policy']=='no-referrer'
    response=client.get(PATH+'/status');assert response.status_code==200
    response=client.post(PATH+'/apply',json=payload(),headers=HEADERS)
    assert response.status_code==200 and response.json()['existing_accounts_changed'] is False
    writer.assert_called_once();reader.assert_called_once()
    for response in (page,response):
        assert 'no-store' in response.headers['cache-control'] and response.headers['vary']=='Cookie'
        assert 'set-cookie' not in response.headers
    assert not any(path.startswith(PATH) for path in client.get('/openapi.json').json()['paths'])
    assert client.post(PATH+'/apply',content='x'*33000,headers=HEADERS).status_code==413


@pytest.mark.parametrize('env',[{}, {'RAG_DATABASE_URL':'auth'}, {'DATABASE_URL':'business','RAG_DATABASE_URL':'auth'}])
def test_no_database_fallback(env):
    with pytest.raises(core.InstallError):core.runtime_dsn(env)

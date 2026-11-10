import csv
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import psycopg
import pytest

from app.auth import deps
from app.auth.service import AuthUser, SessionInfo, LoginRequired
from app.company_admin import prepare, manage, routes, store
from company_registry_fakes import registry

ACTOR=(UUID(int=21),'operator-demo')
HEADERS={'Origin':'https://testserver','X-CSRF-Token':'synthetic-csrf'}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr('dotenv.load_dotenv',lambda *a,**k:False)
    monkeypatch.delenv('COMPANY_ADMIN_ENABLED',raising=False)
    connector=Mock(side_effect=AssertionError('No real DB'))
    monkeypatch.setattr(psycopg,'connect',connector)
    from app.main import app
    monkeypatch.setattr(app,'dependency_overrides',{})
    value=registry();company=value.create_company('SYNTH','검증 고객사',ACTOR)
    app.dependency_overrides[routes.configured_service]=lambda:value
    app.dependency_overrides[deps.require_user]=lambda:SessionInfo(AuthUser(ACTOR[0],ACTOR[1],'user'),'synthetic-csrf')
    monkeypatch.setattr(deps,'current_session',lambda request:app.dependency_overrides[deps.require_user]())
    with TestClient(app,base_url='https://testserver') as c:yield c,app,value,company
    connector.assert_not_called()


def test_search_pagination_and_actor_recording(client):
    c,_,value,company=client
    for i in range(22):value.create_company(f'CODE-{i:02}','검색 회사 '+str(i),ACTOR)
    result=c.get('/api/v1/companies?search=검색&page=2')
    assert result.status_code==200 and result.json()['total']==22 and len(result.json()['items'])==2
    assert c.get('/api/v1/companies?search=%25').json()['total']==0
    assert 'no-store' in result.headers['cache-control']
    assert value.repository.history[0]['actor_label']=='operator-demo'


@pytest.mark.parametrize('role',['customer','unexpected',None])
def test_all_routes_require_operator_before_data_access(client,role):
    c,app,_,company=client
    def session():
        if role is None:raise LoginRequired()
        return SessionInfo(AuthUser(ACTOR[0],'synthetic',role),'synthetic-csrf')
    app.dependency_overrides[deps.require_user]=session
    app.dependency_overrides[routes.configured_service]=lambda:pytest.fail('No registry access for forbidden users')
    root='/api/v1/companies';identity=company['id'];child=uuid4()
    paths=[('GET',root),('GET',root+'/status'),('GET',root+'/'+identity),('POST',root),('PUT',root+'/'+identity),
           ('POST',f'{root}/{identity}/contacts'),('PUT',f'{root}/{identity}/contacts/{child}'),
           ('POST',f'{root}/{identity}/equipment'),('PUT',f'{root}/{identity}/equipment/{child}')]
    for method,path in paths:
        assert c.request(method,path,json={} if method!='GET' else None,headers=HEADERS).status_code==(401 if role is None else 403)


def test_write_origin_csrf_extra_fields_and_size(client):
    c,_,_,company=client;path='/api/v1/companies';payload={'code':'NEW','name':'추가 회사'}
    for headers in [{},{'Origin':'https://evil.example','X-CSRF-Token':'synthetic-csrf'},{'Origin':'https://testserver','X-CSRF-Token':'wrong'}]:
        assert c.post(path,json=payload,headers=headers).status_code==403
    response=c.post(path,json={**payload,'role':'admin','secret':'do-not-echo'},headers=HEADERS)
    assert response.status_code==422 and 'do-not-echo' not in response.text
    for method,p in [('POST',path),('PUT',path+'/'+company['id'])]:
        assert c.request(method,p,content='x'*33000,headers=HEADERS).status_code==413
    assert c.post(path,json=payload,headers=HEADERS).status_code==201
    assert c.post(path,json=payload,headers=HEADERS).status_code==409


def test_contact_registration_confirmation_placeholder_and_cross_company(client):
    c,_,value,company=client;path='/api/v1/companies/'+company['id'];other=value.create_company('OTHER','다른 회사',ACTOR)
    for email,confirmed in [('real@example.org',False),('demo@example.invalid',True),('wrong',True)]:
        assert c.post(path+'/contacts',json={'email':email,'confirmed':confirmed},headers=HEADERS).status_code==400
    r=c.post(path+'/contacts',json={'email':'REAL@EXAMPLE.ORG','confirmed':True},headers=HEADERS)
    contact=r.json()['contacts'][0];assert contact['email']=='real@example.org' and contact['is_active']
    assert c.put(f"/api/v1/companies/{other['id']}/contacts/{contact['id']}",json={'is_active':False,'expected_version':1},headers=HEADERS).status_code==404
    assert c.put(path+'/contacts/'+contact['id'],json={'is_active':False,'expected_version':1},headers=HEADERS).status_code==200
    assert c.put(path+'/contacts/'+contact['id'],json={'is_active':True,'expected_version':1},headers=HEADERS).status_code==409
    value.repository.contacts[contact['id']]['is_placeholder']=True
    assert c.put(path+'/contacts/'+contact['id'],json={'is_active':True,'expected_version':2},headers=HEADERS).json()['code']=='PLACEHOLDER_CONTACT'


def test_membership_comes_from_company_contact_registration_and_survives_deactivation(client):
    c,_,value,company=client
    path='/api/v1/companies/'+company['id']
    contact=c.post(path+'/contacts',json={'email':'member@example.org','confirmed':True},headers=HEADERS).json()['contacts'][0]
    assert contact['is_registered'] is False
    value.repository.registrations.add(contact['id'])
    other=value.create_company('OTHER','다른 회사',ACTOR)
    other_contact=c.post(f"/api/v1/companies/{other['id']}/contacts",json={'email':'member@example.org','confirmed':True},headers=HEADERS).json()['contacts'][0]
    assert other_contact['is_registered'] is False
    assert c.get(path).json()['contacts'][0]['is_registered'] is True
    items={item['id']:item for item in c.get('/api/v1/companies').json()['items']}
    assert items[company['id']]['registered_contacts']==1 and items[company['id']]['active_contacts']==1
    assert items[other['id']]['registered_contacts']==0
    forged=c.put(path+'/contacts/'+contact['id'],json={'is_active':True,'expected_version':1,'is_registered':False},headers=HEADERS)
    assert forged.status_code==422
    changed=c.put(path+'/contacts/'+contact['id'],json={'is_active':False,'expected_version':1},headers=HEADERS).json()
    assert changed['contacts'][0]['is_registered'] is True and changed['contacts'][0]['is_active'] is False
    item=next(item for item in c.get('/api/v1/companies').json()['items'] if item['id']==company['id'])
    assert item['registered_contacts']==0 and item['active_contacts']==0


def test_production_membership_read_uses_contact_identity_without_mutating_registration():
    connection=MagicMock();work=store.Work(connection)
    work.company=Mock(return_value={'id':UUID(int=1)})
    work.one=Mock(return_value={})
    work.rows=Mock(return_value=[])
    work.detail(UUID(int=1),1)
    sql,params=work.rows.call_args_list[0].args
    assert 'EXISTS(' in sql and 'claim_access.registration' in sql and 'r.contact_id=c.id' in sql
    assert 'login_id' not in sql and params==(UUID(int=1),)
    connection.execute.assert_not_called()


def test_quantity_idempotence_stale_edits_and_equipment_scoping(client):
    c,_,value,company=client;path='/api/v1/companies/'+company['id']
    body={'model_name':' MODEL-A ','serial_number':None,'manufacturing_site':None,'is_confirmed':False,'quantity':3,'request_id':str(uuid4())}
    for quantity in [0,101,True,'2']:
        assert c.post(path+'/equipment',json={**body,'quantity':quantity},headers=HEADERS).status_code==422
    assert c.post(path+'/equipment',json={**body,'serial_number':'001'},headers=HEADERS).status_code==400
    for _ in range(2):assert c.post(path+'/equipment',json=body,headers=HEADERS).json()['equipment_summary']['total']==3
    assert len([v for v in value.repository.history if v['event']=='equipment.created'])==1
    assert c.post(path+'/equipment',json={**body,'quantity':2},headers=HEADERS).status_code==409
    detail=c.get(path).json();item=detail['equipment'][0]
    edit={'model_name':item['model_name'],'serial_number':'SERIAL-1','manufacturing_site':'공장','is_confirmed':True,'is_active':True,'expected_version':1}
    other=value.create_company('OTHER','다른 회사',ACTOR)
    assert c.put(f"/api/v1/companies/{other['id']}/equipment/{item['id']}",json=edit,headers=HEADERS).status_code==404
    assert c.put(path+'/equipment/'+item['id'],json=edit,headers=HEADERS).json()['equipment_summary']['confirmed']==1
    assert c.put(path+'/equipment/'+item['id'],json=edit,headers=HEADERS).status_code==409
    duplicate={**body,'quantity':1,'serial_number':'SERIAL-1','request_id':str(uuid4())}
    assert c.post(path+'/equipment',json=duplicate,headers=HEADERS).status_code==409
    assert c.get(path).json()['equipment_summary']['total']==3


def test_company_versions_and_disabled_readiness_are_independent_of_smtp(client,monkeypatch):
    c,app,value,company=client;path='/api/v1/companies/'+company['id']
    payload={'name':'변경 회사','is_active':False,'expected_version':1}
    assert c.put(path,json=payload,headers=HEADERS).json()['company']['version']==2
    assert c.put(path,json=payload,headers=HEADERS).status_code==409
    del app.dependency_overrides[routes.configured_service]
    assert c.get('/api/v1/companies/status').json()=={'available':False,'demo':False}
    assert c.get(path).status_code==503
    monkeypatch.setenv('COMPANY_ADMIN_ENABLED','1');monkeypatch.setenv('APP_COOKIE_SECURE','1');monkeypatch.setenv('DATABASE_URL','synthetic')
    monkeypatch.setattr(store.RegistryRepository,'ready',lambda self:True)
    assert routes.configured_service().demo is False


def make_source(tmp_path,rows):
    path=tmp_path/'source.csv'
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['설치고객사명','기종명','호기','제조처']);writer.writerows(rows)
    return path


def test_source_grouping_determinism_conflicts_private_exports_and_validation(tmp_path):
    rows=[['고객A','MODEL','001','공장'],['고객A','MODEL','001','공장'],['고객B','MODEL','001','공장'],['고객A','MODEL','002','공장']]
    source=make_source(tmp_path,rows);original=source.read_bytes();data=prepare.prepare(source)
    assert data['source_rows']==4 and len(data['companies'])==2 and len(data['equipment'])==3 and data['ownership_conflicts']==1
    assert sum(e['needs_review'] for e in data['equipment'])==2
    assert sum(e['reference_count'] for e in data['equipment'])==4
    manage.validate_seed(data);prepare.export(data,tmp_path/'output');assert source.read_bytes()==original
    restored=json.loads((tmp_path/'output/registry-seed.json').read_text(encoding='utf-8'));assert restored==data
    assert all(c['email'].endswith('@example.invalid') for c in data['companies'])
    source=make_source(tmp_path,list(reversed(rows)));reordered=prepare.prepare(source)
    for key in ['companies','equipment','ownership_conflicts']:assert reordered[key]==data[key]
    corrupted=deepcopy(data);corrupted['companies'][0]['email']='real@example.org'
    with pytest.raises(ValueError):manage.validate_seed(corrupted)
    corrupted=deepcopy(data);corrupted['equipment'][0]['reference_count']+=1
    with pytest.raises(ValueError):manage.validate_seed(corrupted)


@pytest.mark.parametrize('value',['=1+2',' +SUM(A1)','-10','@command'])
def test_csv_formula_values_are_literal(value):assert prepare.spreadsheet_safe(value).startswith("'")


def test_bad_source_is_not_silently_truncated_or_accepted(tmp_path):
    for row in [['','MODEL','001',''],['A','x'*121,'001',''],['A','MODEL','00\x001','']]:
        with pytest.raises(ValueError):prepare.prepare(make_source(tmp_path,[row]))


def test_management_requires_explicit_target_before_any_connection(monkeypatch):
    connector=Mock(side_effect=AssertionError('Do not connect before validation'));monkeypatch.setattr(psycopg,'connect',connector)
    monkeypatch.setenv('DATABASE_URL','do-not-use-fallback');monkeypatch.delenv('COMPANY_ADMIN_MIGRATION_DATABASE_URL',raising=False)
    for args in [SimpleNamespace(apply=True,expect_database=None,seed_file=None),SimpleNamespace(apply=False,expect_database='synthetic',seed_file='private.json'),SimpleNamespace(apply=False,expect_database=None,seed_file=None)]:
        with pytest.raises(ValueError):manage.run(args)
    connector.assert_not_called()


def test_production_sql_locks_versions_binds_and_prevents_placeholder_activation():
    connection=MagicMock();work=store.Work(connection);work.company=Mock();work.audit=Mock()
    work.one=Mock(return_value={'version':1,'is_placeholder':True})
    with pytest.raises(Exception) as error:work.contact_state(UUID(int=1),UUID(int=2),True,1,ACTOR)
    assert error.value.code=='PLACEHOLDER_CONTACT';connection.execute.assert_not_called()
    values={'model_name':"MODEL';--",'serial_number':None,'manufacturing_site':None,'is_confirmed':True,'is_active':True,'expected_version':7}
    work.one=Mock(return_value={'id':UUID(int=2)})
    work.update_equipment(UUID(int=1),UUID(int=2),values,ACTOR)
    sql,params=work.one.call_args.args
    assert values['model_name'] not in sql and params[0]==values['model_name'] and params[-1]==7
    assert 'company_id=%s AND version=%s' in sql and 'needs_review=CASE' in sql
    work.company.assert_called_with(UUID(int=1),True)


def test_import_forces_placeholder_inactive_and_unconfirmed_even_with_hostile_flags(tmp_path,monkeypatch):
    data=prepare.prepare(make_source(tmp_path,[['A','MODEL','001','']]));data['companies'][0]['is_active']=True;data['equipment'][0]['is_confirmed']=True
    connection=MagicMock();identity=UUID(int=40)
    one=Mock(side_effect=[None,{'id':identity},None,None])
    monkeypatch.setattr(manage.Work,'one',one);monkeypatch.setattr(manage.Work,'audit',Mock())
    assert manage.import_seed(connection,data)=={'companies_added':1,'equipment_added':1}
    statements=[call.args[0] for call in connection.execute.call_args_list]
    assert any('FALSE,TRUE' in sql for sql in statements)
    assert any("FALSE,%s,'fsr'" in sql for sql in statements)

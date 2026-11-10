from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID
import hashlib

import pytest

from app.auth.service import InvalidCredentials, InvalidLoginId, _HASHER, authenticate, create_user, _failure_key, normalize_login_id
from app.customer_access import manage, store
from app.customer_access.core import AccessError


def test_company_and_existing_email_queries_bind_values_and_do_not_expose_roles():
    work=store.Work(MagicMock());work.one=Mock(return_value={'id':UUID(int=2)})
    assert work.company_exists('DEMO')
    query,params=work.one.call_args.args
    assert 'FOR SHARE' in query and 'is_active' in query and params==('DEMO',)
    work.one.return_value={'present':True}
    assert work.registration_exists(UUID(int=2)) is True
    query,params=work.one.call_args.args
    assert params==(UUID(int=2),UUID(int=2)) and 'u.login_id' in query
    assert 'is_active' not in query
    work.one.return_value={'present':False}
    assert work.registration_exists(UUID(int=2)) is False


def test_database_writes_are_atomic_and_customer_role_is_server_fixed():
    connection=MagicMock()
    connection.transaction.side_effect=lambda:nullcontext()
    def lookup(query, params):
        return {'present': False} if 'SELECT EXISTS' in query else {'email':'contact+tag@example.org'}
    connection.execute.return_value.fetchone.return_value=(UUID(int=90),)
    work=store.Work(connection)
    work.one=Mock(side_effect=lookup)
    work.register_customer(UUID(int=1),'synthetic-password-123','synthetic-v1')
    calls=connection.execute.call_args_list
    user_insert=next(c for c in calls if 'INSERT INTO app_user' in c.args[0])
    assert user_insert.args[1][2]=='customer'
    assert user_insert.args[1][0]=='contact+tag@example.org'
    assert user_insert.args[1][1].startswith('$argon2')
    assert _HASHER.verify('synthetic-password-123',user_insert.args[1][1])
    registration=next(c for c in calls if 'INSERT INTO claim_access.registration' in c.args[0])
    assert registration.args[1]==(UUID(int=90),UUID(int=1),'synthetic-v1')
    assert not any('UPDATE app_user' in c.args[0] for c in calls)


@pytest.mark.parametrize('email',['customer+tag@example.org','a'*64+'@'+'b'*63+'.example.org'])
def test_email_customer_logins_and_failure_keys_fit_existing_failure_schema(email):
    connection=MagicMock();connection.transaction.side_effect=lambda:nullcontext()
    connection.execute.return_value.fetchone.return_value=(UUID(int=22),)
    assert create_user(connection,email,'synthetic-password-123',role='customer').login_id==email
    assert len(_failure_key(email))<=64 and _failure_key(email)!='?'
    row=(UUID(int=22),email,'customer',_HASHER.hash('synthetic-password-123'),True)
    def execute(sql,params=None):
        result=Mock();result.fetchone.return_value=row if 'SELECT id, login_id' in sql else (0,)
        return result
    connection.execute.side_effect=execute
    assert authenticate(connection,email.upper(),'synthetic-password-123','synthetic-client').role=='customer'
    query=next(c for c in connection.execute.call_args_list if 'SELECT id, login_id' in c.args[0])
    assert query.args[1]==(email,)


def test_long_email_failures_are_distinct_and_idn_login_is_canonical():
    prefix='a'*64+'@'
    assert _failure_key(prefix+'first.example.org')!=_failure_key(prefix+'second.example.org')
    assert normalize_login_id('Contact@bücher.de')=='contact@xn--bcher-kva.de'
    assert normalize_login_id('Contact@faß.de')=='contact@xn--fa-hia.de'


def test_customer_requires_email_and_operator_id_rules_remain_unchanged():
    connection=Mock()
    with pytest.raises(InvalidLoginId):create_user(connection,'customer-alias','synthetic-password-123',role='customer')
    with pytest.raises(InvalidLoginId):create_user(connection,'operator+tag@example.org','synthetic-password-123',role='user')
    connection.execute.assert_not_called()


def test_email_migration_requires_explicit_apply_and_target_before_connect(monkeypatch):
    monkeypatch.setenv('CUSTOMER_ACCESS_MIGRATION_DATABASE_URL','synthetic-dsn')
    connector=Mock(side_effect=AssertionError('No DB before explicit authorization'))
    monkeypatch.setattr(manage.psycopg,'connect',connector)
    with pytest.raises(ValueError):manage.run(SimpleNamespace(apply=False,expect_database='synthetic',company_file=None,with_customer_role=False,with_customer_email=True,create_operator=None))
    connector.assert_not_called()


def test_managing_default_dry_run_uses_read_only_transaction_and_no_ddl(monkeypatch):
    monkeypatch.setenv('CUSTOMER_ACCESS_MIGRATION_DATABASE_URL','synthetic-management-dsn')
    connection=MagicMock()
    def execute(sql,params=None):
        result=Mock();result.fetchone.return_value=('synthetic_db',) if 'current_database' in sql else (False,)
        return result
    connection.execute.side_effect=execute
    monkeypatch.setattr(manage.psycopg,'connect',lambda *a,**k:connection)
    connection.__enter__.return_value=connection
    args=SimpleNamespace(apply=False,expect_database=None,company_file=None,with_customer_role=False,create_operator=None)
    assert manage.run(args)=={'mode':'read_only','version_table_present':False}
    queries=[c.args[0] for c in connection.execute.call_args_list]
    assert queries[0]=='SET TRANSACTION READ ONLY'
    assert not any(q.startswith(('CREATE','ALTER','INSERT','UPDATE','DELETE')) for q in queries)


def test_management_requires_explicit_database_before_prompt_or_connection(monkeypatch):
    monkeypatch.setenv('CUSTOMER_ACCESS_MIGRATION_DATABASE_URL','synthetic-management-dsn')
    connector=Mock(side_effect=AssertionError('no connection'))
    prompt=Mock(side_effect=AssertionError('no password prompt'))
    monkeypatch.setattr(manage.psycopg,'connect',connector);monkeypatch.setattr(manage,'getpass',prompt)
    with pytest.raises(ValueError):
        manage.run(SimpleNamespace(apply=True,expect_database=None,company_file=None,with_customer_role=False,create_operator='operator-demo'))
    connector.assert_not_called();prompt.assert_not_called()


def test_readiness_refuses_missing_or_altered_migration(monkeypatch):
    connection=MagicMock();connection.__enter__.return_value=connection
    connection.execute.return_value.fetchone.return_value=('wrong-checksum',)
    monkeypatch.setattr(store.psycopg,'connect',lambda *a,**k:connection)
    assert store.PostgresRepository('synthetic').ready(False) is False
    queries=[c.args[0] for c in connection.execute.call_args_list]
    assert queries[0]=='SET TRANSACTION READ ONLY'
    assert not any(q.startswith(('CREATE','ALTER','INSERT','UPDATE','DELETE')) for q in queries)


def test_registration_stays_closed_until_email_migration_checksum_matches(monkeypatch):
    connection=MagicMock();connection.__enter__.return_value=connection
    hashes={'001':store.migration_checksum(),'002':hashlib.sha256(store.ROLE_MIGRATION.read_text(encoding='utf-8').encode()).hexdigest()}
    def execute(sql,params=None):
        result=Mock()
        result.fetchone.return_value=('app_user',) if 'to_regclass' in sql else ((hashes[params[0]],) if params and params[0] in hashes else None)
        return result
    connection.execute.side_effect=execute
    monkeypatch.setattr(store.psycopg,'connect',lambda *a,**k:connection)
    assert store.PostgresRepository('synthetic').ready(True) is False
    hashes['003']=hashlib.sha256(store.EMAIL_MIGRATION.read_text(encoding='utf-8').encode()).hexdigest()
    assert store.PostgresRepository('synthetic').ready(True) is True
    assert not any(c.args[0].startswith(('CREATE','ALTER','INSERT','UPDATE','DELETE')) for c in connection.execute.call_args_list)


def test_canonical_migration_hash_is_not_windows_newline_dependent(tmp_path,monkeypatch):
    p=tmp_path/'test.sql';p.write_bytes(b'SELECT 1;\r\nSELECT 2;\r\n')
    monkeypatch.setattr(store,'MIGRATION',p)
    assert store.migration_checksum()==hashlib.sha256(b'SELECT 1;\nSELECT 2;\n').hexdigest()


def test_unknown_inquiry_conflict_does_not_overwrite_existing_text():
    connection=MagicMock();work=store.Work(connection)
    work.get_inquiry=Mock(return_value={'id':'one','title':'original','body':'body'})
    with pytest.raises(AccessError):work.put_inquiry('synthetic-token','changed','body','v1')
    connection.execute.assert_not_called()


def test_authentication_rejects_extra_characters_after_maximum_password():
    password='x'*256;connection=MagicMock()
    row=(UUID(int=2),'operator','user',_HASHER.hash(password),True)
    def execute(sql,params=None):
        result=Mock();result.fetchone.return_value=row if 'SELECT id, login_id' in sql else (0,)
        return result
    connection.execute.side_effect=execute
    with pytest.raises(InvalidCredentials):authenticate(connection,'operator',password+'extra','synthetic-client')
    assert not any('UPDATE app_user SET last_login' in c.args[0] for c in connection.execute.call_args_list)

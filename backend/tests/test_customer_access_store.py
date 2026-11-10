from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID
import hashlib

import pytest

from app.auth.service import InvalidCredentials, _HASHER, authenticate
from app.customer_access import manage, store
from app.customer_access.core import AccessError


def test_database_writes_are_atomic_and_customer_role_is_server_fixed():
    connection=MagicMock()
    connection.transaction.side_effect=lambda:nullcontext()
    connection.cursor.return_value.__enter__.return_value.execute.return_value.fetchone.return_value=None
    connection.execute.return_value.fetchone.return_value=(UUID(int=90),)
    work=store.Work(connection)
    work.register_customer(UUID(int=1),'customer-demo','synthetic-password-123','synthetic-v1')
    calls=connection.execute.call_args_list
    user_insert=next(c for c in calls if 'INSERT INTO app_user' in c.args[0])
    assert user_insert.args[1][2]=='customer'
    assert user_insert.args[1][1].startswith('$argon2')
    assert _HASHER.verify('synthetic-password-123',user_insert.args[1][1])
    registration=next(c for c in calls if 'INSERT INTO claim_access.registration' in c.args[0])
    assert registration.args[1]==(UUID(int=90),UUID(int=1),'synthetic-v1')
    assert not any('UPDATE app_user' in c.args[0] for c in calls)


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

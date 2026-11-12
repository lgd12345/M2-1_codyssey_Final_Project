"""Fixed installation on owned local PostgreSQL databases only (--noconftest)."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier

import pytest

from app.auth.service import create_user,create_session,authenticate,get_session,SessionInfo
from app.company_admin import install_core as core
from app.company_admin.store import RegistryRepository
from test_customer_access_postgres import database,no_external_mail,ADMIN_ENV,PASSWORD
from test_company_installation import grant_for
import os

pytestmark=pytest.mark.skipif(not os.getenv(ADMIN_ENV),reason='Explicit disposable local PostgreSQL not configured')


@pytest.fixture
def installer(database):
    with database.connect() as connection:
        user=create_user(connection,'legacy.installer',PASSWORD,role='user')
        token,csrf=create_session(connection,user.id)
        auth=connection.execute('SELECT id,login_id,password_hash,role,is_active,created_at,last_login_at FROM public.app_user').fetchall()
    session=SessionInfo(user,csrf)
    return database,session,grant_for(session),token,auth


def test_real_install_is_read_only_until_apply_and_preserves_auth(installer):
    database,session,grant,token,before=installer
    plan=core.inspect_installation(database.dsn,grant,session)
    assert plan['state']=='ready' and plan['database_create'] and plan['operator_bound']
    assert database.scalar("SELECT to_regnamespace('claim_access') IS NULL")
    result=core.apply_installation(database.dsn,grant,session,plan['target_fingerprint'])
    assert result['state']=='installed' and result['schema_created']
    assert result['existing_accounts_changed'] is result['mail_sent'] is False
    assert database.scalar('SELECT array_agg(version ORDER BY version) FROM claim_access.schema_version')==['001','004']
    assert RegistryRepository(database.dsn).ready()
    with database.connect() as connection:
        assert connection.execute('SELECT id,login_id,password_hash,role,is_active,created_at,last_login_at FROM public.app_user').fetchall()==before
        assert get_session(connection,token).user.id==session.user.id
        assert authenticate(connection,'legacy.installer',PASSWORD,'127.0.0.1').role=='user'
    repeated=core.apply_installation(database.dsn,grant,session,plan['target_fingerprint'])
    assert repeated['state']=='installed' and repeated['schema_created'] is False


def test_changed_target_and_existing_unknown_schema_fail_closed(installer):
    database,session,grant,_,_=installer
    with pytest.raises(core.InstallError) as error:
        core.apply_installation(database.dsn,grant,session,'0'*64)
    assert error.value.code=='INSTALL_TARGET_CHANGED'
    assert database.scalar("SELECT to_regnamespace('claim_access') IS NULL")
    with database.connect() as connection:
        connection.execute('CREATE SCHEMA claim_access; CREATE TABLE claim_access.sentinel(value int); INSERT INTO claim_access.sentinel VALUES(7)')
    plan=core.inspect_installation(database.dsn,grant,session)
    assert plan['state']=='blocked'
    with pytest.raises(core.InstallError):
        core.apply_installation(database.dsn,grant,session,plan['target_fingerprint'])
    assert database.scalar('SELECT value FROM claim_access.sentinel')==7


def test_concurrent_requests_only_create_once(installer):
    database,session,grant,_,_=installer
    plan=core.inspect_installation(database.dsn,grant,session)
    barrier=Barrier(2)
    def install():
        barrier.wait(timeout=5)
        return core.apply_installation(database.dsn,grant,session,plan['target_fingerprint'])['schema_created']
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _:install(),range(2)))==[False,True]
    assert database.scalar('SELECT count(*) FROM claim_access.schema_version')==2
    other=deepcopy(grant);other['release_id']='f'*32
    assert core.inspect_installation(database.dsn,other,session)['state']=='blocked'


def test_failure_after_ddl_rolls_back_new_schema_and_preserves_existing_user(installer,monkeypatch):
    database,session,grant,_,before=installer
    plan=core.inspect_installation(database.dsn,grant,session)
    original=core.apply_schema
    def fail(connection):
        original(connection)
        raise RuntimeError('Synthetic failure after DDL')
    monkeypatch.setattr(core,'apply_schema',fail)
    with pytest.raises(RuntimeError,match='Synthetic failure'):
        core.apply_installation(database.dsn,grant,session,plan['target_fingerprint'])
    assert database.scalar("SELECT to_regnamespace('claim_access') IS NULL")
    with database.connect() as connection:
        assert connection.execute('SELECT id,login_id,password_hash,role,is_active,created_at,last_login_at FROM public.app_user').fetchall()==before

"""Real PostgreSQL tests on explicitly marked, disposable LOCAL databases only.

Run with --noconftest; never set TEST_DATABASE_URL or use an application DB.
The dedicated admin DSN must point at a loopback server and a database carrying
LOCAL_CLUSTER_MARKER. Each test creates and drops only its own new UUID database.
No actual SMTP, AI, deployment data or existing application database is used.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
import os
import secrets
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import aiosmtplib
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest

from app.auth.service import authenticate, create_user
from app.customer_access import manage
from app.customer_access.core import AccessError, AccessService, Settings
from app.customer_access.store import PostgresRepository
from app.company_admin import manage as registry_manage
from app.company_admin.core import RegistryError, RegistryService
from app.company_admin.store import RegistryRepository
from customer_access_fakes import POLICY

LOCAL_CLUSTER_MARKER = 'morrono-disposable-customer-access-verification-v1'
ADMIN_ENV = 'CUSTOMER_ACCESS_TEST_ADMIN_DSN'
pytestmark = pytest.mark.skipif(not os.getenv(ADMIN_ENV), reason='Explicit disposable local PostgreSQL not configured')
AUTH_SQL = Path(__file__).resolve().parents[1]/'migrations/003_auth.sql'
ACTOR = (UUID(int=21), 'synthetic-operator')
PASSWORD = 'synthetic-password-for-postgres'


@dataclass
class Database:
    dsn: str = field(repr=False)
    name: str

    def connect(self):
        return psycopg.connect(self.dsn, connect_timeout=3)

    def scalar(self, query, params=()):
        with self.connect() as connection:
            return connection.execute(query, params).fetchone()[0]


@pytest.fixture(autouse=True)
def no_external_mail(monkeypatch):
    sender = AsyncMock(side_effect=AssertionError('Real mail is forbidden in DB tests'))
    monkeypatch.setattr(aiosmtplib, 'send', sender)
    yield
    sender.assert_not_awaited()


@pytest.fixture
def database(monkeypatch):
    admin_dsn = os.environ[ADMIN_ENV]
    parameters = conninfo_to_dict(admin_dsn)
    loopback = ('127.0.0.1', '::1')
    host = parameters.get('host')
    if (host not in loopback or parameters.get('hostaddr', host) not in loopback
            or not parameters.get('dbname') or parameters.get('service') or os.getenv('PGSERVICE')):
        pytest.fail('Only an explicitly marked loopback test cluster is allowed')
    # libpq hostaddr (including PGHOSTADDR) can override host routing. Pin it to
    # the validated literal instead of relying on a loopback host label alone.
    admin_dsn = make_conninfo(admin_dsn, hostaddr=host)
    with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=3) as admin:
        if admin.execute('SELECT host(inet_server_addr())').fetchone()[0] not in loopback:
            pytest.fail('The observed test server address is not loopback')
        marker = admin.execute("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()").fetchone()[0]
        if marker != LOCAL_CLUSTER_MARKER:
            pytest.fail('The test provisioning database is not marked as disposable')
        name = 'claim_access_verify_' + uuid4().hex + '_test'
        admin.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(name)))
        target = Database(make_conninfo(admin_dsn, dbname=name), name)
        monkeypatch.setenv('CUSTOMER_ACCESS_MIGRATION_DATABASE_URL', target.dsn)
        monkeypatch.setenv('COMPANY_ADMIN_MIGRATION_DATABASE_URL', target.dsn)
        try:
            with target.connect() as connection:
                connection.execute(AUTH_SQL.read_text(encoding='utf-8'))
            yield target
        finally:
            # Only this fixture's successfully created UUID database is removed.
            admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))


def management_args(database, **overrides):
    return SimpleNamespace(**dict(dict(apply=True, expect_database=database.name,
        company_file=None, with_customer_role=True, with_customer_email=True,
        create_operator=None, operator_role='user'), **overrides))


def apply(database):
    manage.run(management_args(database))
    registry_manage.run(SimpleNamespace(apply=True, expect_database=database.name, seed_file=None))


@pytest.fixture
def configured(database):
    apply(database)
    registry = RegistryService(RegistryRepository(database.dsn))
    company = registry.create_company('PG-CHECK', '합성 PostgreSQL 검증 고객사', ACTOR)
    detail = registry.add_contact(company['id'], 'customer+pg@example.org', True, ACTOR)
    access = AccessService(Settings(database.dsn, 'synthetic-secret-for-postgres-at-least-32-characters',
        'a'*16, 'sender@example.org', dict(POLICY), True, smtp_username='sender@example.org'), PostgresRepository(database.dsn))
    return SimpleNamespace(db=database, registry=registry, company=company,
                           contact=detail['contacts'][0], access=access)


def issued(value, purpose='register', email='customer+pg@example.org', client='synthetic-client'):
    proof, identity, recipient, number = value.access.start(purpose, 'PG-CHECK', email, client, POLICY['version'], True)
    # No mail: model only a completed submission so repository behavior is tested.
    value.access.sent(identity, True)
    return proof, number, identity


def test_read_only_management_and_wrong_target_cannot_create_schema(database):
    assert manage.run(management_args(database, apply=False, with_customer_role=False, with_customer_email=False)) == {'mode':'read_only', 'version_table_present':False}
    assert database.scalar("SELECT to_regnamespace('claim_access') IS NULL")
    with pytest.raises(ValueError, match='target mismatch'):
        manage.run(management_args(database, expect_database='a-different-database'))
    assert database.scalar("SELECT to_regnamespace('claim_access') IS NULL")


def test_real_migrations_repeat_safely_and_preserve_existing_operator(database):
    with database.connect() as connection:
        operator = create_user(connection, 'legacy.operator', PASSWORD, role='user')
        before = connection.execute('SELECT password_hash,role FROM app_user WHERE id=%s', (operator.id,)).fetchone()
    assert not PostgresRepository(database.dsn).ready(True)
    apply(database)
    apply(database)
    assert database.scalar("SELECT array_agg(version ORDER BY version) FROM claim_access.schema_version") == ['001','002','003','004']
    assert PostgresRepository(database.dsn).ready(True) and RegistryRepository(database.dsn).ready()
    with database.connect() as connection:
        assert connection.execute('SELECT password_hash,role FROM app_user WHERE id=%s', (operator.id,)).fetchone() == before
        assert authenticate(connection, 'legacy.operator', PASSWORD, '127.0.0.1').id == operator.id


@pytest.mark.parametrize('constraint', ['role', 'login_id'])
def test_unknown_existing_constraint_rolls_back_all_new_ddl(database, constraint):
    with database.connect() as connection:
        connection.execute(sql.SQL('ALTER TABLE app_user DROP CONSTRAINT {}').format(sql.Identifier('app_user_'+constraint+'_check')))
        rule = "CHECK(role IN ('admin','user','custom'))" if constraint=='role' else 'CHECK(char_length(login_id)<=80)'
        connection.execute(sql.SQL('ALTER TABLE app_user ADD CONSTRAINT {} ').format(sql.Identifier('app_user_'+constraint+'_check')) + sql.SQL(rule))
        before = connection.execute("SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='app_user'::regclass ORDER BY conname").fetchall()
    with pytest.raises(psycopg.errors.RaiseException):
        manage.run(management_args(database))
    assert database.scalar("SELECT to_regnamespace('claim_access') IS NULL")
    with database.connect() as connection:
        assert connection.execute("SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='app_user'::regclass ORDER BY conname").fetchall() == before


def test_checksum_mismatch_stays_closed_in_real_database(database):
    apply(database)
    with database.connect() as connection:
        connection.execute("UPDATE claim_access.schema_version SET checksum=%s WHERE version='001'", ('0'*64,))
    assert not PostgresRepository(database.dsn).ready(True)
    assert not RegistryRepository(database.dsn).ready()
    with pytest.raises(ValueError, match='checksum mismatch'):
        manage.run(management_args(database))
    assert database.scalar("SELECT checksum FROM claim_access.schema_version WHERE version='001'") == '0'*64


def test_registration_uses_verified_email_and_updates_operator_read_model(configured):
    value = configured
    proof, number, _ = issued(value)
    assert value.access.verify_registration(proof, number, POLICY['version'], True) == {'state':'verified', 'email':'customer+pg@example.org'}
    assert value.access.register(proof, number, PASSWORD, POLICY['version'], True)['state'] == 'registered'
    assert value.db.scalar("SELECT count(*) FROM app_user WHERE role='customer' AND login_id='customer+pg@example.org'") == 1
    assert value.registry.detail(value.company['id'])['contacts'][0]['is_registered']
    assert value.registry.list('', 1)['items'][0]['registered_contacts'] == 1
    with value.db.connect() as connection:
        user = authenticate(connection, 'customer+pg@example.org', PASSWORD, '127.0.0.1')
    with value.access.repository.transaction() as work:
        assert work.customer_profile(user.id)['id'] == str(value.company['id'])
    value.registry.contact_state(value.company['id'], value.contact['id'], False, value.contact['version'], ACTOR)
    assert value.registry.list('', 1)['items'][0]['registered_contacts'] == 1
    with value.access.repository.transaction() as work:
        assert work.customer_profile(user.id) is None


def test_concurrent_registration_produces_only_one_account_and_membership(configured):
    value = configured
    proof, number, _ = issued(value)
    barrier = Barrier(2)
    def register():
        barrier.wait(timeout=5)
        try:
            return value.access.register(proof, number, PASSWORD, POLICY['version'], True)['state']
        except AccessError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: register(), range(2)))
    assert sorted(results) == ['ACCESS_CODE_INVALID', 'registered']
    assert value.db.scalar('SELECT count(*) FROM app_user') == 1
    assert value.db.scalar('SELECT count(*) FROM claim_access.registration') == 1


def test_membership_insert_failure_does_not_leave_orphan_user(configured):
    value = configured
    proof, number, _ = issued(value)
    with value.db.connect() as connection:
        connection.execute("""CREATE FUNCTION claim_access.reject_membership() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'Synthetic membership failure'; END $$;
            CREATE TRIGGER reject_membership BEFORE INSERT ON claim_access.registration
            FOR EACH ROW EXECUTE FUNCTION claim_access.reject_membership();""")
    with pytest.raises(psycopg.errors.RaiseException):
        value.access.register(proof, number, PASSWORD, POLICY['version'], True)
    assert value.db.scalar('SELECT count(*) FROM app_user') == 0
    assert value.db.scalar('SELECT count(*) FROM claim_access.registration') == 0


def test_guest_inquiry_is_idempotent_and_cannot_cross_contact_sessions(configured):
    value = configured
    proof, number, _ = issued(value, 'guest')
    token, state = value.access.guest(proof, number, POLICY['version'], True)
    result = value.access.inquiry(token, '합성 문의', '합성 본문', state['csrf_token'], POLICY['version'], True)
    assert value.access.inquiry(token, '합성 문의', '합성 본문', state['csrf_token'], POLICY['version'], True) == result
    with pytest.raises(AccessError) as error:
        value.access.inquiry(token, '다른 제목', '합성 본문', state['csrf_token'], POLICY['version'], True)
    assert error.value.code == 'INQUIRY_CONFLICT'
    value.registry.add_contact(value.company['id'], 'other+pg@example.org', True, ACTOR)
    proof2, number2, _ = issued(value, 'guest', 'other+pg@example.org', 'other-client')
    token2, _ = value.access.guest(proof2, number2, POLICY['version'], True)
    assert value.access.inquiry(token2) is None
    assert value.access.inquiry(token)['id'] == result['id']
    value.registry.contact_state(value.company['id'], value.contact['id'], False, value.contact['version'], ACTOR)
    assert not value.access.guest_state(token)['authenticated']
    with pytest.raises(AccessError) as error:
        value.access.inquiry(token)
    assert error.value.code == 'GUEST_REQUIRED'


def test_equipment_retry_and_stale_company_update_do_not_duplicate_or_overwrite(configured):
    value = configured
    payload = dict(request_id=uuid4(), model_name='SYNTHETIC-CNC', serial_number=None, manufacturing_site=None, quantity=3, is_confirmed=False)
    first = value.registry.add_equipment(value.company['id'], payload, ACTOR)
    again = value.registry.add_equipment(value.company['id'], payload, ACTOR)
    assert first['equipment_summary']['active'] == again['equipment_summary']['active'] == 3
    assert value.db.scalar('SELECT count(*) FROM claim_access.equipment') == 3
    value.registry.update_company(value.company['id'], '수정된 합성 고객사', True, 1, ACTOR)
    with pytest.raises(RegistryError) as error:
        value.registry.update_company(value.company['id'], '과거 값 덮어쓰기', True, 1, ACTOR)
    assert error.value.code == 'REGISTRY_CONFLICT'
    assert value.registry.detail(value.company['id'])['company']['name'] == '수정된 합성 고객사'


def test_runtime_dml_role_can_serve_customers_but_cannot_change_schema_or_ledger(configured):
    value = configured
    role = 'verify_runtime_' + uuid4().hex
    runtime_password = secrets.token_urlsafe(24)
    with value.db.connect() as connection:
        connection.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}').format(sql.Identifier(role), sql.Literal(runtime_password)))
        connection.execute(sql.SQL('GRANT USAGE ON SCHEMA public,claim_access TO {}').format(sql.Identifier(role)))
        grants = [
            ('SELECT,INSERT,UPDATE', 'public.app_user,public.app_session,claim_access.company,claim_access.contact,claim_access.equipment'),
            ('SELECT,INSERT,DELETE', 'public.app_login_failure'),
            ('SELECT,INSERT,UPDATE,DELETE', 'claim_access.challenge'),
            ('SELECT,INSERT', 'claim_access.registration,claim_access.guest_session,claim_access.inquiry,claim_access.registry_audit'),
            ('SELECT', 'claim_access.schema_version'),
        ]
        for privileges, tables in grants:
            connection.execute(sql.SQL('GRANT '+privileges+' ON '+tables+' TO {}').format(sql.Identifier(role)))
        # SELECT FOR UPDATE also requires UPDATE on at least one column.
        # The session row lock serializes inquiry submissions; keep that lock.
        connection.execute(sql.SQL('GRANT UPDATE(expires_at) ON claim_access.guest_session TO {}').format(sql.Identifier(role)))
        connection.execute(sql.SQL('GRANT USAGE ON ALL SEQUENCES IN SCHEMA public,claim_access TO {}').format(sql.Identifier(role)))
    try:
        runtime_dsn = make_conninfo(value.db.dsn, user=role, password=runtime_password)
        value.access = AccessService(replace(value.access.settings, database_url=runtime_dsn), PostgresRepository(runtime_dsn))
        value.registry = RegistryService(RegistryRepository(runtime_dsn))
        assert value.access.repository.ready(True) and value.registry.repository.ready()
        proof, number, _ = issued(value)
        assert value.access.register(proof, number, PASSWORD, POLICY['version'], True)['state'] == 'registered'
        with psycopg.connect(runtime_dsn) as connection:
            assert authenticate(connection, 'customer+pg@example.org', PASSWORD, '127.0.0.1').role == 'customer'
            for forbidden in ('CREATE TABLE public.forbidden_table(id int)',
                              "UPDATE claim_access.schema_version SET checksum='tampered'",
                              'DROP TABLE public.app_user'):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    with connection.transaction():
                        connection.execute(forbidden)
        detail = value.registry.add_contact(value.company['id'], 'runtime+pg@example.org', True, ACTOR)
        assert len(detail['contacts']) == 2
        proof, number, _ = issued(value, 'guest', 'runtime+pg@example.org', 'runtime-client')
        token, state = value.access.guest(proof, number, POLICY['version'], True)
        assert value.access.inquiry(token, '최소 권한 시험', '합성 본문', state['csrf_token'], POLICY['version'], True)['title'] == '최소 권한 시험'
    finally:
        with value.db.connect() as connection:
            connection.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
            connection.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))

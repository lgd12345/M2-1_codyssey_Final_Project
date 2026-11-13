"""Real pg_dump/pg_restore tests on owned disposable loopback databases only.

Run with --noconftest. Reuse the marked-cluster guard and synthetic fixtures;
never restore over an existing application database or invoke real SMTP/AI.
"""
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest

from app.auth.service import authenticate, create_user, create_session, get_session
from app.customer_access.core import AccessService
from app.customer_access.store import PostgresRepository
from app.company_admin.core import RegistryService
from app.company_admin.store import RegistryRepository
from test_customer_access_postgres import (
    ADMIN_ENV, ACTOR, PASSWORD, POLICY, Database, apply, issued,
    database, configured, no_external_mail,
)

pytestmark = pytest.mark.skipif(not os.getenv(ADMIN_ENV), reason='Explicit disposable local PostgreSQL not configured')
_TABLES = {
    'public': ('app_user', 'app_session', 'app_login_failure'),
    'claim_access': ('schema_version', 'company', 'contact', 'challenge',
                     'registration', 'guest_session', 'inquiry', 'equipment', 'registry_audit'),
}


@pytest.fixture
def restored_database(database):
    # database already verifies loopback routing and the disposable cluster marker.
    # This second database is newly created EMPTY, never an existing target.
    name = 'claim_access_restore_' + uuid4().hex + '_test'
    with psycopg.connect(database.dsn, autocommit=True, connect_timeout=3) as connection:
        connection.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(name)))
        restored = Database(make_conninfo(database.dsn, dbname=name), name)
        try:
            yield restored
        finally:
            connection.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))


@pytest.fixture
def pg_tools(tmp_path):
    configured_bin = os.getenv('CUSTOMER_ACCESS_TEST_PG_BIN')
    if not configured_bin:
        pytest.skip('Official PostgreSQL client binary directory not configured')
    binary = Path(configured_bin).resolve()
    suffix = '.exe' if os.name == 'nt' else ''
    for name in ('pg_dump', 'pg_restore'):
        assert (binary/(name+suffix)).is_file(), 'Required PostgreSQL client is missing'

    def run(tool, target, *arguments, success=True):
        assert tool in ('pg_dump', 'pg_restore')
        parameters = conninfo_to_dict(target.dsn)
        parameters.setdefault('port', '5432')
        host = parameters.get('host')
        assert host in ('127.0.0.1', '::1')
        assert parameters.get('hostaddr', host) == host
        assert not parameters.get('service')
        assert parameters['dbname'] == target.name
        assert parameters.get('user') and parameters.get('password'), 'Backup tests require explicit disposable credentials'
        assert target.name.startswith(('claim_access_verify_', 'claim_access_restore_')) and target.name.endswith('_test')
        # Prevent inherited libpq routing/service/options from changing the target.
        env = {key:value for key,value in os.environ.items() if not key.upper().startswith('PG')}
        def escape(value):
            return value.replace('\\', '\\\\').replace(':', '\\:')
        passfile = tmp_path/'disposable-test.pgpass'
        passfile.write_text(':'.join(escape(parameters[key]) for key in ('host','port','dbname','user','password'))+'\n', encoding='utf-8')
        passfile.chmod(0o600)
        env.update(PGHOST=host, PGHOSTADDR=host, PGPORT=parameters['port'],
                   PGUSER=parameters['user'], PGPASSFILE=str(passfile), PGCONNECT_TIMEOUT='3')
        try:
            result = subprocess.run([str(binary/(tool+suffix)), '--no-password',
                '--dbname', target.name, *map(str, arguments)], env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        finally:
            passfile.unlink(missing_ok=True)
        output = result.stderr.decode('utf-8', errors='replace').replace(parameters['password'], '<redacted>')
        (tmp_path/(tool+'-stderr.txt')).write_text(output, encoding='utf-8')
        assert (result.returncode == 0) is success, tool+' returned an unexpected status; inspect private test stderr'
        return result
    return run


def fingerprint(target):
    """Compare all synthetic rows without printing passwords, tokens or bodies."""
    result = {}
    with target.connect() as connection:
        for schema, tables in _TABLES.items():
            for table in tables:
                relation = schema+'.'+table
                if not connection.execute('SELECT to_regclass(%s) IS NOT NULL', (relation,)).fetchone()[0]:
                    continue
                rows = connection.execute(sql.SQL(
                    'SELECT pg_catalog.to_jsonb(r)::text FROM {} r ORDER BY pg_catalog.to_jsonb(r)::text'
                ).format(sql.Identifier(schema, table))).fetchall()
                result[relation] = (len(rows), hashlib.sha256('\n'.join(row[0] for row in rows).encode()).hexdigest())
        result['sequences'] = connection.execute(
            "SELECT schemaname,sequencename,last_value FROM pg_catalog.pg_sequences "
            "WHERE schemaname IN ('public','claim_access') ORDER BY schemaname,sequencename"
        ).fetchall()
    return result


def test_pre_migration_backup_restores_legacy_login_to_new_database(database, restored_database, pg_tools, tmp_path):
    with database.connect() as connection:
        operator = create_user(connection, 'legacy.backup', PASSWORD, role='user')
        token, _ = create_session(connection, operator.id)
    before = fingerprint(database)
    archive = tmp_path/'before-migration.dump'
    pg_tools('pg_dump', database, '--format=custom', '--file', archive)
    assert archive.read_bytes()[:5] == b'PGDMP'
    apply(database)
    migrated = fingerprint(database)
    pg_tools('pg_restore', restored_database, '--single-transaction', '--exit-on-error', archive)
    assert fingerprint(restored_database) == before
    assert fingerprint(database) == migrated
    assert restored_database.scalar("SELECT to_regnamespace('claim_access') IS NULL")
    with restored_database.connect() as connection:
        assert authenticate(connection, 'legacy.backup', PASSWORD, '127.0.0.1').id == operator.id
        assert get_session(connection, token).user.role == 'user'


def test_backup_restores_all_customer_data_and_excludes_later_changes(configured, restored_database, pg_tools, tmp_path):
    value = configured
    with value.db.connect() as connection:
        operator = create_user(connection, 'legacy.backup', PASSWORD, role='user')
        operator_token, _ = create_session(connection, operator.id)
    proof, number, _ = issued(value)
    value.access.register(proof, number, PASSWORD, POLICY['version'], True)
    value.registry.add_contact(value.company['id'], 'guest+backup@example.org', True, ACTOR)
    proof, number, _ = issued(value, 'guest', 'guest+backup@example.org', 'backup-client')
    guest_token, state = value.access.guest(proof, number, POLICY['version'], True)
    inquiry = value.access.inquiry(guest_token, '복원 시험', '합성 문의 본문', state['csrf_token'], POLICY['version'], True)
    equipment = dict(request_id=uuid4(), model_name='BACKUP-CNC', serial_number=None,
                     manufacturing_site='합성 설치 장소', quantity=2, is_confirmed=True)
    value.registry.add_equipment(value.company['id'], equipment, ACTOR)
    before = fingerprint(value.db)
    archive = tmp_path/'customer-data.dump'
    pg_tools('pg_dump', value.db, '--format=custom', '--file', archive)
    value.registry.create_company('AFTER-BACKUP', '백업 이후 합성 고객사', ACTOR)
    source_after = fingerprint(value.db)
    pg_tools('pg_restore', restored_database, '--single-transaction', '--exit-on-error', archive)
    assert fingerprint(restored_database) == before
    assert fingerprint(value.db) == source_after
    assert restored_database.scalar("SELECT count(*) FROM claim_access.company WHERE code='AFTER-BACKUP'") == 0
    assert PostgresRepository(restored_database.dsn).ready(True)
    assert RegistryRepository(restored_database.dsn).ready()
    with restored_database.connect() as connection:
        assert authenticate(connection, 'legacy.backup', PASSWORD, '127.0.0.1').id == operator.id
        assert get_session(connection, operator_token).user.role == 'user'
        customer = authenticate(connection, 'customer+pg@example.org', PASSWORD, '127.0.0.1')
        assert customer.role == 'customer'
    restored_access = AccessService(replace(value.access.settings, database_url=restored_database.dsn), PostgresRepository(restored_database.dsn))
    restored_registry = RegistryService(RegistryRepository(restored_database.dsn))
    assert restored_access.inquiry(guest_token) == inquiry
    with restored_access.repository.transaction() as work:
        assert work.customer_profile(customer.id)['id'] == str(value.company['id'])
    assert restored_registry.list('', 1)['items'][0]['registered_contacts'] == 1
    restored_registry.add_equipment(value.company['id'], equipment, ACTOR)
    assert restored_database.scalar('SELECT count(*) FROM claim_access.equipment') == 2
    previous_audit_id = restored_database.scalar('SELECT max(id) FROM claim_access.registry_audit')
    restored_registry.create_company('RESTORED-NEW', '복원 후 합성 고객사', ACTOR)
    assert restored_database.scalar('SELECT max(id) FROM claim_access.registry_audit') > previous_audit_id


def test_restore_error_rolls_back_instead_of_leaving_partial_schema(configured, restored_database, pg_tools, tmp_path):
    archive = tmp_path/'restore-conflict.dump'
    pg_tools('pg_dump', configured.db, '--format=custom', '--file', archive)
    # Intentional collision in this fixture's NEW destination, never production.
    with restored_database.connect() as connection:
        connection.execute('CREATE TABLE public.app_user(marker text)')
        connection.execute("INSERT INTO public.app_user VALUES ('must-survive-failed-restore')")
    pg_tools('pg_restore', restored_database, '--single-transaction', '--exit-on-error', archive, success=False)
    assert restored_database.scalar("SELECT to_regnamespace('claim_access') IS NULL")
    assert restored_database.scalar('SELECT marker FROM public.app_user') == 'must-survive-failed-restore'

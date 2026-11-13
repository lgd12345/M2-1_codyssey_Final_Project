"""Explicit, fixed customer-auth migration on the already installed registry DB."""
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path

import psycopg
from psycopg import sql

from app.company_admin import install_core as registry
from app.customer_access.store import ROLE_MIGRATION, EMAIL_MIGRATION

ACTION = 'install_customer_002_003'
GRANT_FILE = Path(__file__).with_name('customer-installation-grant.json')
MIGRATIONS = {'002': ROLE_MIGRATION, '003': EMAIL_MIGRATION}
MARKER = 'morrono-customer-install-v1:'


def storage_status():
    """Inspect only fixed app data paths; no host sources or environment values."""
    candidates = ('/app/data','/data')
    try:
        mounts = []
        for line in Path('/proc/self/mountinfo').read_text().splitlines():
            fields = line.split()
            separator = fields.index('-')
            mounts.append((Path(fields[4]),fields[separator+1]))
        result = {}
        for candidate in candidates:
            path = Path(candidate).resolve()
            parents = [(mount,kind) for mount,kind in mounts if path==mount or mount in path.parents]
            mount,kind = max(parents,key=lambda entry:len(str(entry[0])))
            result[candidate] = {'mounted':str(mount)!='/' and kind not in ('overlay','tmpfs','ramfs'),
                                 'exists':path.is_dir(),'writable':path.is_dir() and os.access(path,os.W_OK)}
        return result
    except (OSError,ValueError,IndexError):
        return {'verified':False}


def checksums():
    return {key: hashlib.sha256(path.read_text(encoding='utf-8').encode()).hexdigest()
            for key, path in MIGRATIONS.items()}


def read_grant(session, host):
    return registry.read_grant(session, host, grant_file=GRANT_FILE, action=ACTION,
                               expected_checksums=checksums())


def inspect_connection(connection, grant, session):
    base = registry.inspect_connection(connection, grant, session)
    state = 'blocked'
    present = connection.execute("SELECT to_regclass('claim_access.schema_version') IS NOT NULL").fetchone()[0]
    if present and base['operator_bound']:
        versions = dict(connection.execute('SELECT version,checksum FROM claim_access.schema_version').fetchall())
        prerequisite = registry.checksums()
        actual = {key: versions[key] for key in MIGRATIONS if key in versions}
        expected = checksums()
        constraints = connection.execute("""SELECT conname,pg_catalog.pg_get_constraintdef(oid),convalidated,
            pg_catalog.obj_description(oid,'pg_constraint') FROM pg_catalog.pg_constraint
            WHERE conrelid='public.app_user'::regclass
            AND conname IN ('app_user_role_check','app_user_login_id_check') ORDER BY conname""").fetchall()
        if all(versions.get(key)==value for key,value in prerequisite.items()) and len(constraints)==2:
            old = {r[0]:r[1] for r in constraints}
            if not actual and all(r[2] for r in constraints) and old == {
                'app_user_role_check': "CHECK ((role = ANY (ARRAY['admin'::text, 'user'::text])))",
                'app_user_login_id_check': "CHECK ((login_id ~ '^[a-z0-9._@-]{3,64}$'::text))",
            }:
                state = 'ready'
            if actual == expected and all(r[2] for r in constraints):
                try:
                    marker = constraints[0][3]
                    receipt = json.loads(marker[len(MARKER):]) if isinstance(marker,str) and marker.startswith(MARKER) else {}
                except ValueError:
                    receipt = {}
                binding = {'action':ACTION,'release_id':grant['release_id'],
                           'subject_sha256':registry.subject_hash(session),
                           'target_fingerprint':base['target_fingerprint'],
                           'constraints_sha256':hashlib.sha256(json.dumps([r[:3] for r in constraints]).encode()).hexdigest()}
                if isinstance(receipt,dict) and all(receipt.get(k)==v for k,v in binding.items()):
                    state = 'installed'
    return {**base,'state':state,'versions':['002','003']}


def inspect_installation(dsn, grant, session):
    with psycopg.connect(dsn,connect_timeout=3) as connection:
        connection.execute('SET TRANSACTION READ ONLY')
        connection.execute("SET LOCAL statement_timeout='3s'")
        connection.execute("SET LOCAL lock_timeout='1s'")
        return {**inspect_connection(connection,grant,session),'private_storage':storage_status()}


def apply_installation(dsn, grant, session, target_fingerprint):
    with psycopg.connect(dsn,connect_timeout=3) as connection:
        connection.execute("SET LOCAL statement_timeout='10s'")
        connection.execute("SET LOCAL lock_timeout='2s'")
        connection.execute('SELECT pg_advisory_xact_lock(338176981015)')
        before = inspect_connection(connection,grant,session)
        if not hmac.compare_digest(before['target_fingerprint'],target_fingerprint):
            raise registry.InstallError('INSTALL_TARGET_CHANGED',409,'점검한 대상이 달라졌습니다.')
        if before['state']=='installed':
            return {**before,'schema_created':False,'existing_accounts_changed':False,'mail_sent':False}
        if before['state']!='ready':
            raise registry.InstallError('INSTALL_PRECONDITION_FAILED',409,'구조 또는 이력이 예상과 달라 적용하지 않았습니다.')
        # Both constraints and ledger entries commit together; no account DML.
        for version,path in MIGRATIONS.items():
            connection.execute(path.read_text(encoding='utf-8'))
            connection.execute('INSERT INTO claim_access.schema_version(version,checksum) VALUES (%s,%s)',
                               (version,checksums()[version]))
        constraints = connection.execute("""SELECT conname,pg_catalog.pg_get_constraintdef(oid),convalidated
            FROM pg_catalog.pg_constraint WHERE conrelid='public.app_user'::regclass
            AND conname IN ('app_user_role_check','app_user_login_id_check') ORDER BY conname""").fetchall()
        receipt = {'action':ACTION,'release_id':grant['release_id'],
                   'subject_sha256':registry.subject_hash(session),'target_fingerprint':target_fingerprint,
                   'constraints_sha256':hashlib.sha256(json.dumps(constraints).encode()).hexdigest(),
                   'applied_at':datetime.now(timezone.utc).isoformat()}
        connection.execute(sql.SQL('COMMENT ON CONSTRAINT app_user_login_id_check ON public.app_user IS {}').format(
            sql.Literal(MARKER+json.dumps(receipt,separators=(',',':')))))
        after = inspect_connection(connection,grant,session)
        if after['state']!='installed':
            raise registry.InstallError('INSTALL_VERIFICATION_FAILED',503,'검증 실패로 전체 변경을 취소했습니다.')
    return {**after,'schema_created':False,'existing_accounts_changed':False,'mail_sent':False}

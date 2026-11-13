"""Single fixed, deployment-authorized registry installation; no shell or input SQL."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

import psycopg
from psycopg import sql

from app.auth.service import AuthError
from app.company_admin.manage import apply_schema
from app.company_admin.store import registry_checksum
from app.customer_access.store import migration_checksum

GRANT_FILE = Path(__file__).with_name('installation-grant.json')
ACTION = 'install_registry_001_004'
_MARKER = 'morrono-registry-install-v1:'
_TABLES = ('schema_version','company','contact','challenge','registration',
           'guest_session','inquiry','equipment','registry_audit')


class InstallError(AuthError):
    def __init__(self, code='INSTALL_NOT_AUTHORIZED', status=403,
                 message='이 계정에 유효한 설치 승인이 없습니다.'):
        self.code, self.status_code, self.message = code, status, message
        super().__init__(message)


def subject_hash(session):
    return hashlib.sha256(str(session.user.id).encode()).hexdigest()


def checksums():
    return {'001':migration_checksum(), '004':registry_checksum()}


def read_grant(session, host, now=None, *, grant_file=None, action=None, expected_checksums=None):
    """Only a reviewed source grant can authorize this identity for <= one hour."""
    now = now or datetime.now(timezone.utc)
    grant_file = GRANT_FILE if grant_file is None else grant_file
    action = ACTION if action is None else action
    expected_checksums = checksums() if expected_checksums is None else expected_checksums
    try:
        if grant_file.stat().st_size > 4096:
            raise ValueError
        grant = json.loads(grant_file.read_text(encoding='utf-8'))
        required = {'version','action','release_id','subject_sha256','approval_sha256',
                    'issued_at','expires_at','origin','migration_checksums'}
        if not isinstance(grant,dict) or set(grant)!=required or type(grant['version']) is not int or grant['version']!=1:
            raise ValueError
        if grant['action']!=action or grant['migration_checksums']!=expected_checksums:
            raise ValueError
        for name,size in [('release_id',32),('subject_sha256',64),('approval_sha256',64)]:
            if not isinstance(grant[name],str) or not re.fullmatch('[0-9a-f]{'+str(size)+'}',grant[name]):
                raise ValueError
        if not hmac.compare_digest(grant['subject_sha256'],subject_hash(session)):
            raise ValueError
        issued = datetime.fromisoformat(grant['issued_at'])
        expires = datetime.fromisoformat(grant['expires_at'])
        if (issued.utcoffset()!=timedelta(0) or expires.utcoffset()!=timedelta(0)
                or not timedelta(0)<expires-issued<=timedelta(hours=1)
                or issued>now+timedelta(minutes=2) or now>=expires):
            raise ValueError
        origin = urlsplit(grant['origin'])
        if (origin.scheme!='https' or not origin.hostname or origin.username or origin.password
                or origin.path or origin.query or origin.fragment
                or origin.netloc.casefold()!=host.casefold()):
            raise ValueError
        return grant
    except (OSError,ValueError,TypeError,KeyError,AttributeError):
        raise InstallError() from None


def runtime_dsn(env):
    dsn = env.get('DATABASE_URL','').strip()
    auth = (env.get('RAG_DATABASE_URL','') or dsn).strip()
    if not dsn or auth!=dsn:
        raise InstallError('INSTALL_TARGET_UNAVAILABLE',409,'인증·업무 DB 설정을 먼저 확인해야 합니다.')
    return dsn


def inspect_connection(connection, grant, session):
    row = connection.execute("""SELECT d.oid,d.datname,pg_catalog.inet_server_addr()::text,
        pg_catalog.inet_server_port(),current_user,
        pg_catalog.has_database_privilege(d.oid,'CREATE')
        FROM pg_catalog.pg_database d WHERE d.datname=pg_catalog.current_database()""").fetchone()
    fingerprint = hashlib.sha256(json.dumps(row[:5],separators=(',',':')).encode()).hexdigest()
    # Existing authentication must resolve to the actual public table on this target.
    auth = connection.execute("""SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relname='app_user' AND c.relkind IN ('r','p')
        AND c.oid=pg_catalog.to_regclass('app_user'))""").fetchone()[0]
    if auth:
        auth = connection.execute("""SELECT EXISTS(SELECT 1 FROM public.app_user
            WHERE id=%s AND is_active AND role IN ('admin','user'))""",(session.user.id,)).fetchone()[0]
    namespace = connection.execute("""SELECT pg_catalog.obj_description(oid,'pg_namespace')
        FROM pg_catalog.pg_namespace WHERE nspname='claim_access'""").fetchone()
    state = 'ready' if namespace is None and row[5] and auth else 'blocked'
    if namespace and isinstance(namespace[0],str) and namespace[0].startswith(_MARKER):
        try:
            receipt = json.loads(namespace[0][len(_MARKER):])
        except ValueError:
            receipt = {}
        if not isinstance(receipt,dict):
            receipt = {}
        expected = {'release_id':grant['release_id'], 'subject_sha256':subject_hash(session),
                    'target_fingerprint':fingerprint, 'action':ACTION}
        if auth and all(receipt.get(key)==value for key,value in expected.items()):
            tables = connection.execute("""SELECT c.relname,c.relkind,pg_catalog.row_security_active(c.oid)
                FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='claim_access' AND c.relname=ANY(%s::text[]) LIMIT 10""",(list(_TABLES),)).fetchall()
            if (len(tables)==len(_TABLES) and {r[0] for r in tables}==set(_TABLES)
                    and all(r[1]=='r' and not r[2] for r in tables)):
                versions = connection.execute("SELECT version,checksum FROM claim_access.schema_version WHERE version=ANY(%s::text[]) LIMIT 3",(list(checksums()),)).fetchall()
                if len(versions)==2 and dict(versions)==checksums():
                    state = 'installed'
    return {'state':state, 'target_fingerprint':fingerprint,
            'database_create':bool(row[5]), 'operator_bound':bool(auth),
            'release_id':grant['release_id'], 'expires_at':grant['expires_at'],
            'versions':['001','004']}


def inspect_installation(dsn, grant, session):
    with psycopg.connect(dsn,connect_timeout=3) as connection:
        connection.execute('SET TRANSACTION READ ONLY')
        connection.execute("SET LOCAL statement_timeout='3s'")
        connection.execute("SET LOCAL lock_timeout='1s'")
        if connection.execute('SHOW transaction_read_only').fetchone()!=('on',):
            raise InstallError('INSTALL_READ_ONLY_UNCONFIRMED',503,'읽기 전용 점검을 확인하지 못했습니다.')
        return inspect_connection(connection,grant,session)


def apply_installation(dsn, grant, session, target_fingerprint):
    with psycopg.connect(dsn,connect_timeout=3) as connection:
        connection.execute("SET LOCAL statement_timeout='10s'")
        connection.execute("SET LOCAL lock_timeout='2s'")
        connection.execute('SELECT pg_advisory_xact_lock(338176981015)')
        before = inspect_connection(connection,grant,session)
        if not hmac.compare_digest(before['target_fingerprint'],target_fingerprint):
            raise InstallError('INSTALL_TARGET_CHANGED',409,'점검한 대상이 달라졌습니다. 다시 확인해 주세요.')
        if before['state']=='installed':
            return {**before,'schema_created':False,'existing_accounts_changed':False,'mail_sent':False}
        if before['state']!='ready':
            raise InstallError('INSTALL_PRECONDITION_FAILED',409,'기존 구조 또는 권한이 예상과 달라 적용하지 않았습니다.')
        # Strict creation closes the race with a non-cooperating schema creator.
        connection.execute('CREATE SCHEMA claim_access')
        apply_schema(connection)
        receipt = {'release_id':grant['release_id'],'subject_sha256':subject_hash(session),
                   'target_fingerprint':target_fingerprint,'action':ACTION,
                   'applied_at':datetime.now(timezone.utc).isoformat()}
        connection.execute(sql.SQL('COMMENT ON SCHEMA claim_access IS {}').format(
            sql.Literal(_MARKER+json.dumps(receipt,separators=(',',':')))))
        after = inspect_connection(connection,grant,session)
        if after['state']!='installed':
            raise InstallError('INSTALL_VERIFICATION_FAILED',503,'적용 검증에 실패해 전체 작업을 취소했습니다.')
    return {**after,'schema_created':True,'existing_accounts_changed':False,'mail_sent':False}

"""Operator preflight: fixed metadata reads, never business rows or DB writes."""
from collections.abc import Mapping
import hashlib

import psycopg

from app.company_admin.store import REGISTRY_MIGRATION
from app.customer_access.store import MIGRATION, ROLE_MIGRATION, EMAIL_MIGRATION


_MIGRATIONS = {
    '001': MIGRATION, '002': ROLE_MIGRATION,
    '003': EMAIL_MIGRATION, '004': REGISTRY_MIGRATION,
}
_TABLES = (
    'schema_version', 'company', 'contact', 'challenge', 'registration',
    'guest_session', 'inquiry', 'equipment', 'registry_audit',
)
_RELATIONS_SQL = """
    SELECT c.relname, c.relkind, pg_catalog.row_security_active(c.oid)
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='claim_access' AND c.relname=ANY(%s::pg_catalog.text[])
    LIMIT 10
"""
_AUTH_SQL = """
    SELECT c.relkind, c.oid=pg_catalog.to_regclass('app_user'),
           pg_catalog.pg_has_role(c.relowner, 'USAGE')
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND c.relname='app_user'
"""


def _database(dsn):
    result = {
        'connection': 'not_configured' if not dsn else 'unverified',
        'read_only': False,
        'schema': 'unverified',
        'required_tables': 'unverified',
        'auth_table': 'unverified',
        'ledger': 'unverified',
        'migrations': dict.fromkeys(_MIGRATIONS, 'unverified'),
        'permission_checks': {'database_create': None, 'auth_table_owner': None},
    }
    if not dsn:
        return result
    try:
        with psycopg.connect(dsn, connect_timeout=3, autocommit=True) as connection:
            result['connection'] = 'ok'
            with connection.transaction():
                connection.execute('SET TRANSACTION READ ONLY')
                connection.execute("SET LOCAL statement_timeout = '2s'")
                connection.execute("SET LOCAL lock_timeout = '500ms'")
                if connection.execute("SHOW transaction_read_only").fetchone() != ('on',):
                    return result
                result['read_only'] = True
                present = connection.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname='claim_access'), "
                    "pg_catalog.has_database_privilege(pg_catalog.current_database(), 'CREATE')"
                ).fetchone()
                result['schema'] = 'present' if present[0] else 'missing'
                result['permission_checks']['database_create'] = present[1]
                rows = connection.execute(_RELATIONS_SQL, (list(_TABLES),)).fetchall()
                tables = {name: (kind, rls) for name, kind, rls in rows}
                result['required_tables'] = (
                    'missing' if set(tables) != set(_TABLES) else
                    'present' if all(kind in ('r', 'p') for kind, _ in tables.values()) else
                    'unsupported_relation'
                )
                auth = connection.execute(_AUTH_SQL).fetchone()
                result['auth_table'] = (
                    'missing' if auth is None else
                    'public_visible' if auth[0] in ('r', 'p') and auth[1] else 'unverified'
                )
                result['permission_checks']['auth_table_owner'] = auth[2] if auth is not None else None
                ledger = tables.get('schema_version')
                if ledger is None:
                    result['ledger'] = 'missing'
                    result['migrations'] = dict.fromkeys(_MIGRATIONS, 'missing')
                    return result
                # Do not execute SELECT against a view, foreign table or RLS ledger.
                if ledger[0] not in ('r', 'p') or ledger[1]:
                    result['ledger'] = 'unverified'
                    return result
                result['ledger'] = 'unreadable'
                rows = connection.execute(
                    'SELECT version,checksum FROM claim_access.schema_version '
                    'WHERE version=ANY(%s::pg_catalog.text[]) LIMIT 5',
                    (list(_MIGRATIONS),),
                ).fetchall()
                versions = dict(rows)
                if len(rows) != len(versions) or len(rows) > len(_MIGRATIONS):
                    return result
                result['ledger'] = 'readable'
                for version, path in _MIGRATIONS.items():
                    expected = hashlib.sha256(path.read_text(encoding='utf-8').encode('utf-8')).hexdigest()
                    result['migrations'][version] = (
                        'missing' if version not in versions else
                        'matched' if versions[version] == expected else 'mismatch'
                    )
    except (psycopg.Error, OSError, ValueError):
        # Never expose/log exception text, DSNs, role names, addresses or data.
        if result['connection'] != 'ok':
            result['connection'] = 'failed'
    return result


def inspect_readiness(env: Mapping[str, str]):
    business = env.get('DATABASE_URL', '').strip()
    auth = (env.get('RAG_DATABASE_URL', '') or business).strip()
    compatibility = (
        'business_not_configured' if not business else
        'auth_not_configured' if not auth else
        'same_connection_settings' if auth == business else 'different_connection_settings'
    )
    return {
        'scope': 'read_only_preflight',
        'database': _database(business),
        # Same DSN settings satisfy the current registration config gate only.
        # Different strings do not prove different physical databases.
        'auth_configuration': compatibility,
        'feature_flags': {
            'company_admin': env.get('COMPANY_ADMIN_ENABLED') == '1',
            'customer_access': env.get('CUSTOMER_ACCESS_ENABLED') == '1',
            'customer_registration': env.get('CUSTOMER_REGISTRATION_ENABLED') == '1',
            'secure_cookie': env.get('APP_COOKIE_SECURE') == '1',
        },
        # Presence only: never return values, lengths, file paths or hashes.
        # Nonempty settings are not proof of valid SMTP or policy content.
        'server_settings_present': {
            name: bool(env.get(variable, '').strip()) for name, variable in (
                ('smtp_username', 'CUSTOMER_SMTP_USERNAME'),
                ('smtp_password', 'CUSTOMER_SMTP_PASSWORD'),
                ('verification_secret', 'CUSTOMER_ACCESS_SECRET'),
                ('policy_file', 'CUSTOMER_ACCESS_POLICY_FILE'),
            )
        },
        'write_checks_performed': False,
    }

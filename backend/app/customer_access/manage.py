"""Explicit management only; never called by web startup.

Run from /app (or backend): python -m app.customer_access.manage --help
The default performs no writes. Apply/seed require the exact expected DB name.
"""
import argparse
import json
import os
from pathlib import Path
import hashlib
from getpass import getpass

import psycopg

from app.customer_access.core import company_code, email_address
from app.customer_access.store import MIGRATION, ROLE_MIGRATION, EMAIL_MIGRATION, migration_checksum
from app.auth.service import create_user


def run(args):
    with_email = getattr(args, 'with_customer_email', False)
    dsn = os.environ.get('CUSTOMER_ACCESS_MIGRATION_DATABASE_URL', '').strip()
    if not dsn:
        raise ValueError('CUSTOMER_ACCESS_MIGRATION_DATABASE_URL is required; no fallback')
    if (args.apply or args.company_file or args.with_customer_role or with_email) and not args.expect_database:
        raise ValueError('Writes require --expect-database and --apply')
    if args.company_file and not args.apply:
        raise ValueError('Company/contact changes require --apply')
    if args.with_customer_role and not args.apply:
        raise ValueError('Role migration requires --apply')
    if with_email and not args.apply:
        raise ValueError('Email migration requires --apply')
    if args.create_operator and (not args.apply or args.company_file or args.with_customer_role or with_email):
        raise ValueError('Operator creation is a separate explicit --apply operation')
    operator_password = getpass('New operator password: ') if args.create_operator else None
    # Read and validate the whole private input before starting a DB transaction.
    company = None
    if args.company_file:
        source = json.loads(Path(args.company_file).read_text(encoding='utf-8'))
        name = source['name'].strip()
        if not 1 <= len(name) <= 120 or not isinstance(source['emails'], list) or len(source['emails']) > 100:
            raise ValueError('Invalid company input')
        company = (company_code(source['code']), name, sorted({email_address(x) for x in source['emails']}))
    with psycopg.connect(dsn, connect_timeout=3) as connection:
        if not args.apply:
            connection.execute('SET TRANSACTION READ ONLY')
        connection.execute("SET LOCAL statement_timeout='10s'")
        connection.execute("SET LOCAL lock_timeout='2s'")
        actual = connection.execute('SELECT current_database()').fetchone()[0]
        if args.expect_database and actual != args.expect_database:
            raise ValueError('Database target mismatch')
        if not args.apply:
            present = connection.execute("SELECT to_regclass('claim_access.schema_version') IS NOT NULL").fetchone()[0]
            return {'mode': 'read_only', 'version_table_present': present}
        if args.create_operator:
            create_user(connection, args.create_operator, operator_password, role=args.operator_role)
            return {'mode': 'applied', 'operator_created': True}
        connection.execute('SELECT pg_advisory_xact_lock(338176981015)')
        connection.execute('CREATE SCHEMA IF NOT EXISTS claim_access')
        connection.execute('CREATE TABLE IF NOT EXISTS claim_access.schema_version(version TEXT PRIMARY KEY,checksum TEXT NOT NULL,applied_at TIMESTAMPTZ NOT NULL DEFAULT now())')
        row = connection.execute('SELECT checksum FROM claim_access.schema_version WHERE version=%s', ('001',)).fetchone()
        checksum = migration_checksum()
        if row and row[0] != checksum:
            raise ValueError('Applied migration checksum mismatch')
        if not row:
            connection.execute(MIGRATION.read_text(encoding='utf-8'))
            connection.execute('INSERT INTO claim_access.schema_version(version,checksum) VALUES (%s,%s)', ('001', checksum))
        if args.with_customer_role:
            role_checksum = hashlib.sha256(ROLE_MIGRATION.read_text(encoding='utf-8').encode('utf-8')).hexdigest()
            role_row = connection.execute('SELECT checksum FROM claim_access.schema_version WHERE version=%s', ('002',)).fetchone()
            if role_row and role_row[0] != role_checksum:
                raise ValueError('Role migration checksum mismatch')
            if not role_row:
                connection.execute(ROLE_MIGRATION.read_text(encoding='utf-8'))
                connection.execute('INSERT INTO claim_access.schema_version(version,checksum) VALUES (%s,%s)', ('002', role_checksum))
        if with_email:
            expected_role = hashlib.sha256(ROLE_MIGRATION.read_text(encoding='utf-8').encode('utf-8')).hexdigest()
            role_row = connection.execute('SELECT checksum FROM claim_access.schema_version WHERE version=%s', ('002',)).fetchone()
            if not role_row or role_row[0] != expected_role:
                raise ValueError('Apply and verify the role migration first')
            checksum = hashlib.sha256(EMAIL_MIGRATION.read_text(encoding='utf-8').encode('utf-8')).hexdigest()
            row = connection.execute('SELECT checksum FROM claim_access.schema_version WHERE version=%s', ('003',)).fetchone()
            if row and row[0] != checksum:
                raise ValueError('Email migration checksum mismatch')
            if not row:
                connection.execute(EMAIL_MIGRATION.read_text(encoding='utf-8'))
                connection.execute('INSERT INTO claim_access.schema_version(version,checksum) VALUES (%s,%s)', ('003', checksum))
        if company:
            code, name, emails = company
            existing = connection.execute('SELECT id,name,is_active FROM claim_access.company WHERE code=%s FOR UPDATE', (code,)).fetchone()
            if existing:
                if existing[1] != name or not existing[2]:
                    raise ValueError('Company conflict; existing company is not overwritten or reactivated')
                identity = existing[0]
            else:
                identity = connection.execute('INSERT INTO claim_access.company(code,name) VALUES (%s,%s) RETURNING id', (code, name)).fetchone()[0]
            for email in emails:
                connection.execute('INSERT INTO claim_access.contact(company_id,email) VALUES (%s,%s) ON CONFLICT(company_id,email) DO NOTHING', (identity, email))
        return {'mode': 'applied', 'version': '001', 'company_input_processed': company is not None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expect-database')
    parser.add_argument('--company-file', help='Private JSON file containing code/name/emails; never commit it')
    parser.add_argument('--with-customer-role', action='store_true', help='Explicitly extend public.app_user role constraint on the selected auth DB')
    parser.add_argument('--with-customer-email', action='store_true', help='Explicitly allow customer email logins; requires the verified role migration')
    parser.add_argument('--create-operator', metavar='LOGIN_ID', help='Issue an operator account on the explicitly selected auth DB; password is entered privately')
    parser.add_argument('--operator-role', choices=('user', 'admin'), default='user', help='user is ordinary operator; admin also has restricted system management access')
    args = parser.parse_args()
    try:
        result = run(args)
    except Exception:
        # No connection strings, credentials, company names or email input in logs.
        parser.exit(1, 'Customer access management failed; verify target, input, privileges and migration version.\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()

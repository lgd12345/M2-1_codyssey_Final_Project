"""Explicit registry schema/seed management. Default is read-only, never startup."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from uuid import UUID

import psycopg

from app.customer_access.store import MIGRATION,migration_checksum
from app.customer_access.core import company_code
from app.company_admin.core import text
from app.company_admin.store import REGISTRY_MIGRATION,registry_checksum,Work


def validate_seed(data):
    if data.get('format')!='morrono-registry-demo-v1':raise ValueError('Unknown seed format')
    if not re.fullmatch('[0-9a-f]{64}',data.get('source_sha256','')):raise ValueError('Missing source checksum')
    companies=data['companies'];equipment=data['equipment']
    if len(companies)>10000 or len(equipment)>100000:raise ValueError('Seed too large')
    codes=set();identities=set();mapping={}
    for c in companies:
        identity=str(UUID(c['id']));code=company_code(c['code']);text(c['name'])
        if code in codes or identity in identities:raise ValueError('Duplicate company')
        if c['email']!=code.lower()+'@example.invalid':raise ValueError('Only reserved inactive demo emails are imported')
        codes.add(code);identities.add(identity);mapping[identity]=code
    keys=set();identities=set()
    for e in equipment:
        identity=str(UUID(e['id']));owner=str(UUID(e['company_id']))
        if owner not in mapping or e['company_code']!=mapping[owner]:raise ValueError('Unknown company')
        key=e['source_key']
        if not re.fullmatch('[0-9a-f]{64}',key) or key in keys or identity in identities:raise ValueError('Duplicate equipment')
        for field in ('model_name','serial_number'):text(e[field])
        text(e.get('manufacturing_site'),optional=True)
        if type(e['reference_count']) is not int or e['reference_count']<1:raise ValueError('Invalid reference count')
        if type(e['needs_review']) is not bool:raise ValueError('Invalid review flag')
        keys.add(key);identities.add(identity)
    if sum(e['reference_count'] for e in equipment)!=data['source_rows']:raise ValueError('Source counts do not reconcile')
    return data


def import_seed(connection,data):
    work=Work(connection);mapped={};new_companies=0;new_equipment=0
    for c in data['companies']:
        row=work.one('SELECT id,name FROM claim_access.company WHERE code=%s FOR UPDATE',(c['code'],))
        if row:
            if row['name']!=c['name']:raise ValueError('Company conflict; never overwrite')
            identity=row['id']
        else:
            row=work.one('INSERT INTO claim_access.company(code,name) VALUES (%s,%s) RETURNING id',(c['code'],c['name']))
            identity=row['id'];new_companies+=1
            work.audit(identity,(None,'시연 데이터 등록'),'company.imported',identity,{'source_sha256':data['source_sha256']})
        mapped[c['id']]=identity
        row=work.one('SELECT is_placeholder,is_active FROM claim_access.contact WHERE company_id=%s AND email=%s',(identity,c['email']))
        if row:
            if not row['is_placeholder'] or row['is_active']:raise ValueError('Contact conflict')
        else:
            connection.execute('INSERT INTO claim_access.contact(company_id,email,is_active,is_placeholder) VALUES (%s,%s,FALSE,TRUE)',(identity,c['email']))
    for e in data['equipment']:
        identity=mapped[e['company_id']]
        row=work.one('SELECT company_id,model_name,serial_number FROM claim_access.equipment WHERE source_key=%s',(e['source_key'],))
        if row:
            if str(row['company_id'])!=str(identity) or row['model_name']!=e['model_name'] or row['serial_number']!=e['serial_number']:
                raise ValueError('Equipment conflict; never overwrite')
            continue
        connection.execute('''INSERT INTO claim_access.equipment(id,company_id,model_name,serial_number,manufacturing_site,
            is_confirmed,needs_review,source_kind,source_key,reference_count)
            VALUES (%s,%s,%s,%s,%s,FALSE,%s,'fsr',%s,%s)''',
            (UUID(e['id']),identity,e['model_name'],e['serial_number'],e.get('manufacturing_site'),e['needs_review'],e['source_key'],e['reference_count']))
        work.audit(identity,(None,'시연 데이터 등록'),'equipment.imported',UUID(e['id']),{'source':'fsr'})
        new_equipment+=1
    return {'companies_added':new_companies,'equipment_added':new_equipment}


def run(args):
    if (args.apply or args.seed_file) and not args.expect_database:raise ValueError('Exact database name required')
    if args.seed_file and not args.apply:raise ValueError('Seed requires explicit apply')
    dsn=os.getenv('COMPANY_ADMIN_MIGRATION_DATABASE_URL','').strip()
    if not dsn:raise ValueError('Explicit management DSN required')
    seed=validate_seed(json.loads(Path(args.seed_file).read_text(encoding='utf-8'))) if args.seed_file else None
    with psycopg.connect(dsn,connect_timeout=3) as c:
        if not args.apply:c.execute('SET TRANSACTION READ ONLY')
        c.execute("SET LOCAL statement_timeout='10s'");c.execute("SET LOCAL lock_timeout='2s'")
        actual=c.execute('SELECT current_database()').fetchone()[0]
        if args.expect_database and actual!=args.expect_database:raise ValueError('Wrong target database')
        if not args.apply:
            return {'mode':'read_only','version_table_present':c.execute("SELECT to_regclass('claim_access.schema_version') IS NOT NULL").fetchone()[0]}
        c.execute('SELECT pg_advisory_xact_lock(338176981015)')
        c.execute('CREATE SCHEMA IF NOT EXISTS claim_access')
        c.execute('CREATE TABLE IF NOT EXISTS claim_access.schema_version(version TEXT PRIMARY KEY,checksum TEXT NOT NULL,applied_at TIMESTAMPTZ NOT NULL DEFAULT now())')
        for version,path,checksum in [('001',MIGRATION,migration_checksum()),('004',REGISTRY_MIGRATION,registry_checksum())]:
            row=c.execute('SELECT checksum FROM claim_access.schema_version WHERE version=%s',(version,)).fetchone()
            if row and row[0]!=checksum:raise ValueError('Migration checksum mismatch')
            if not row:
                c.execute(path.read_text(encoding='utf-8'))
                c.execute('INSERT INTO claim_access.schema_version(version,checksum) VALUES (%s,%s)',(version,checksum))
        result=import_seed(c,seed) if seed else {}
        return {'mode':'applied','version':'004',**result}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true');parser.add_argument('--expect-database');parser.add_argument('--seed-file')
    args=parser.parse_args()
    try:result=run(args)
    except Exception:parser.exit(1,'Registry management failed; verify target, privileges, input and version.\n')
    print(json.dumps(result))


if __name__=='__main__':main()

from contextlib import contextmanager
import hashlib
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from app.customer_access.store import Work as AccessWork, MIGRATION, migration_checksum
from app.company_admin.core import RegistryError, conflict, missing

REGISTRY_MIGRATION=Path(__file__).with_name('004_registry.sql')


def registry_checksum():
    return hashlib.sha256(REGISTRY_MIGRATION.read_text(encoding='utf-8').encode()).hexdigest()


class RegistryRepository:
    def __init__(self,dsn):self.dsn=dsn

    def ready(self):
        try:
            with psycopg.connect(self.dsn,connect_timeout=3) as c:
                c.execute('SET TRANSACTION READ ONLY')
                c.execute("SET LOCAL statement_timeout='2s'")
                for version,expected in [('001',migration_checksum()),('004',registry_checksum())]:
                    row=c.execute('SELECT checksum FROM claim_access.schema_version WHERE version=%s',(version,)).fetchone()
                    if not row or row[0]!=expected:return False
                return True
        except (psycopg.Error,OSError):return False

    @contextmanager
    def transaction(self):
        with psycopg.connect(self.dsn,connect_timeout=3) as c:
            c.execute("SET LOCAL statement_timeout='3s'")
            c.execute("SET LOCAL lock_timeout='2s'")
            yield Work(c)


class Work(AccessWork):
    def rows(self,sql,params=()):
        from psycopg.rows import dict_row
        with self.connection.cursor(row_factory=dict_row) as c:return c.execute(sql,params).fetchall()

    def company(self,identity,lock=False):
        row=self.one('SELECT * FROM claim_access.company WHERE id=%s'+(' FOR UPDATE' if lock else ''),(identity,))
        if not row:raise missing()
        return row

    def list_companies(self,search,page):
        pattern='%'+search.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        params=(pattern,pattern)
        total=self.one('SELECT count(*) AS n FROM claim_access.company WHERE name ILIKE %s OR code ILIKE %s',params)['n']
        items=self.rows('''SELECT p.*,
            (SELECT count(*) FROM claim_access.contact c WHERE c.company_id=p.id AND c.is_active) AS active_contacts,
            (SELECT count(*) FROM claim_access.equipment e WHERE e.company_id=p.id AND e.is_active) AS equipment_count,
            (SELECT count(*) FROM claim_access.equipment e WHERE e.company_id=p.id AND e.is_active AND NOT e.is_confirmed) AS unconfirmed_count
            FROM claim_access.company p WHERE p.name ILIKE %s OR p.code ILIKE %s ORDER BY p.name,p.id LIMIT 20 OFFSET %s''',(*params,(page-1)*20))
        return {'items':items,'total':total,'page':page,'page_size':20}

    def detail(self,identity,page):
        company=self.company(identity)
        contacts=self.rows('SELECT * FROM claim_access.contact WHERE company_id=%s ORDER BY is_placeholder,email',(identity,))
        summary=self.one('''SELECT count(*) AS total,count(*) FILTER(WHERE is_active) AS active,
            count(*) FILTER(WHERE is_active AND is_confirmed) AS confirmed,
            count(*) FILTER(WHERE is_active AND needs_review) AS needs_review FROM claim_access.equipment WHERE company_id=%s''',(identity,))
        equipment=self.rows('SELECT * FROM claim_access.equipment WHERE company_id=%s ORDER BY model_name,serial_number NULLS LAST,id LIMIT 20 OFFSET %s',(identity,(page-1)*20))
        audit=self.rows('SELECT event,actor_label,fields,created_at FROM claim_access.registry_audit WHERE company_id=%s ORDER BY id DESC LIMIT 20',(identity,))
        return {'company':company,'contacts':contacts,'equipment':equipment,'equipment_summary':summary,'equipment_page':page,'page_size':20,'audit':audit}

    def audit(self,company,actor,event,target,fields):
        self.connection.execute('''INSERT INTO claim_access.registry_audit(company_id,actor_id,actor_label,event,target_id,fields)
            VALUES (%s,%s,%s,%s,%s,%s)''',(company,actor[0],actor[1],event,target,Jsonb(fields)))

    def create_company(self,code,name,actor):
        row=self.one('INSERT INTO claim_access.company(code,name) VALUES (%s,%s) RETURNING *',(code,name))
        self.audit(row['id'],actor,'company.created',row['id'],{'fields':['code','name']})
        return row

    def update_company(self,identity,name,active,version,actor):
        self.company(identity,True)
        row=self.one('UPDATE claim_access.company SET name=%s,is_active=%s,version=version+1 WHERE id=%s AND version=%s RETURNING id',(name,active,identity,version))
        if not row:raise conflict()
        self.audit(identity,actor,'company.updated',identity,{'fields':['name','is_active']})

    def add_contact(self,identity,email,actor):
        self.company(identity,True)
        if self.one('SELECT count(*) AS n FROM claim_access.contact WHERE company_id=%s',(identity,))['n']>=100:
            raise RegistryError(message='연락처는 회사당 100개까지 등록할 수 있습니다.')
        row=self.one('INSERT INTO claim_access.contact(company_id,email) VALUES (%s,%s) RETURNING id',(identity,email))
        self.audit(identity,actor,'contact.created',row['id'],{'fields':['email']})

    def contact_state(self,identity,contact,active,version,actor):
        self.company(identity,True)
        row=self.one('SELECT * FROM claim_access.contact WHERE id=%s AND company_id=%s FOR UPDATE',(contact,identity))
        if not row:raise missing()
        if row['version']!=version:raise conflict()
        if active and row['is_placeholder']:
            raise RegistryError('PLACEHOLDER_CONTACT','시연용 이메일은 활성화할 수 없습니다. 실제 이메일을 등록해 주세요.')
        self.connection.execute('UPDATE claim_access.contact SET is_active=%s,version=version+1 WHERE id=%s',(active,contact))
        self.audit(identity,actor,'contact.updated',contact,{'fields':['is_active']})

    def add_equipment(self,identity,key,payload_hash,values,actor):
        self.company(identity,True)
        existing=self.rows('SELECT batch_hash FROM claim_access.equipment WHERE company_id=%s AND batch_key=%s',(identity,key))
        if existing:
            if len(existing)!=values['quantity'] or any(e['batch_hash']!=payload_hash for e in existing):raise conflict()
            return
        for i in range(values['quantity']):
            self.connection.execute('''INSERT INTO claim_access.equipment(company_id,model_name,serial_number,manufacturing_site,is_confirmed,source_kind,batch_key,batch_index,batch_hash)
                VALUES (%s,%s,%s,%s,%s,'manual',%s,%s,%s)''',(identity,values['model_name'],values['serial_number'],values['manufacturing_site'],values['is_confirmed'],key,i,payload_hash))
        self.audit(identity,actor,'equipment.created',key,{'quantity':values['quantity']})

    def update_equipment(self,identity,equipment,v,actor):
        self.company(identity,True)
        row=self.one('''UPDATE claim_access.equipment SET model_name=%s,serial_number=%s,manufacturing_site=%s,
            is_confirmed=%s,is_active=%s,needs_review=CASE WHEN %s THEN FALSE ELSE needs_review END,
            version=version+1 WHERE id=%s AND company_id=%s AND version=%s RETURNING id''',
            (v['model_name'],v['serial_number'],v['manufacturing_site'],v['is_confirmed'],v['is_active'],v['is_confirmed'],equipment,identity,v['expected_version']))
        if not row:
            if not self.one('SELECT id FROM claim_access.equipment WHERE id=%s AND company_id=%s',(equipment,identity)):raise missing()
            raise conflict()
        self.audit(identity,actor,'equipment.updated',equipment,{'fields':['model_name','serial_number','manufacturing_site','is_confirmed','is_active']})

"""Private local review/test adapter. Never mounted by app.main."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4, UUID

import psycopg

from app.company_admin.core import RegistryService, RegistryError, conflict, missing


class MemoryRegistry:
    def __init__(self, seed=None):
        self._lock=RLock()
        self.companies={};self.contacts={};self.equipment={};self.history=[];self.batches={}
        for c in (seed or {}).get('companies',[]):
            c=dict(c);email=c.pop('email');c.update(version=1)
            self.companies[c['id']]=c
            identity=str(uuid4())
            self.contacts[identity]={'id':identity,'company_id':c['id'],'email':email,'is_active':False,'is_placeholder':True,'version':1}
        for e in (seed or {}).get('equipment',[]):
            self.equipment[e['id']]={**e,'version':1}

    @contextmanager
    def transaction(self):
        with self._lock:
            before={k:deepcopy(v) for k,v in self.__dict__.items() if k!='_lock'}
            try:yield self
            except Exception:
                self.__dict__.update(before)
                raise

    def company(self, identity):
        value=self.companies.get(str(identity))
        if value is None:raise missing()
        return value

    def audit(self, identity, actor, event):
        self.history.append({'company_id':str(identity),'event':event,'actor_label':actor[1],
                             'actor_id':str(actor[0]),'created_at':datetime.now(timezone.utc).isoformat()})

    def list_companies(self, search, page):
        items=[]
        for c in sorted(self.companies.values(),key=lambda c:(c['name'],c['id'])):
            if search.casefold() not in c['name'].casefold() and search.casefold() not in c['code'].casefold():continue
            es=[e for e in self.equipment.values() if e['company_id']==c['id'] and e['is_active']]
            items.append({**c,'equipment_count':len(es),'unconfirmed_count':sum(not e['is_confirmed'] for e in es),
                          'active_contacts':sum(v['company_id']==c['id'] and v['is_active'] for v in self.contacts.values())})
        return {'items':deepcopy(items[(page-1)*20:page*20]),'page':page,'page_size':20,'total':len(items)}

    def detail(self, identity, page):
        c=self.company(identity);identity=str(identity)
        es=sorted([e for e in self.equipment.values() if e['company_id']==identity],key=lambda e:(e['model_name'],e['serial_number'] or '\uffff',e['id']))
        return deepcopy({'company':c,'contacts':sorted([v for v in self.contacts.values() if v['company_id']==identity],key=lambda v:(v['is_placeholder'],v['email'])),
                         'equipment':es[(page-1)*20:page*20],'equipment_page':page,'page_size':20,
                         'equipment_summary':{'total':len(es),'active':sum(e['is_active'] for e in es),
                           'confirmed':sum(e['is_confirmed'] and e['is_active'] for e in es),
                           'needs_review':sum(e['needs_review'] and e['is_active'] for e in es)},
                         'audit':[v for v in reversed(self.history) if v['company_id']==identity][:20]})

    def create_company(self, code, name, actor):
        if any(c['code']==code for c in self.companies.values()):raise psycopg.errors.UniqueViolation()
        identity=str(uuid4());value={'id':identity,'code':code,'name':name,'is_active':True,'version':1}
        self.companies[identity]=value;self.audit(identity,actor,'company.created')
        return deepcopy(value)

    def update_company(self, identity, name, active, version, actor):
        c=self.company(identity)
        if c['version']!=version:raise conflict()
        c.update(name=name,is_active=active,version=version+1);self.audit(identity,actor,'company.updated')

    def add_contact(self, identity, email, actor):
        self.company(identity);identity=str(identity)
        contacts=[c for c in self.contacts.values() if c['company_id']==identity]
        if any(c['email']==email for c in contacts):raise psycopg.errors.UniqueViolation()
        if len(contacts)>=100:raise RegistryError()
        key=str(uuid4());self.contacts[key]={'id':key,'company_id':identity,'email':email,'is_placeholder':False,'is_active':True,'version':1}
        self.audit(identity,actor,'contact.created')

    def contact_state(self, identity, contact, active, version, actor):
        self.company(identity);c=self.contacts.get(str(contact))
        if not c or c['company_id']!=str(identity):raise missing()
        if c['version']!=version:raise conflict()
        if active and c['is_placeholder']:raise RegistryError('PLACEHOLDER_CONTACT','시연용 이메일은 활성화할 수 없습니다.')
        c.update(is_active=active,version=version+1);self.audit(identity,actor,'contact.updated')

    def unique_equipment(self, identity, model, serial, excluding=None):
        if serial and any(e['id']!=excluding and e['company_id']==str(identity) and e['model_name']==model and e['serial_number']==serial for e in self.equipment.values()):raise psycopg.errors.UniqueViolation()

    def add_equipment(self, identity, key, payload_hash, values, actor):
        self.company(identity);identity=str(identity);batch=(identity,str(key))
        if batch in self.batches:
            if self.batches[batch]!=payload_hash:raise conflict()
            return
        self.unique_equipment(identity,values['model_name'],values['serial_number'])
        for _ in range(values['quantity']):
            item=str(uuid4());self.equipment[item]={'id':item,'company_id':identity,**{k:v for k,v in values.items() if k!='quantity'},
                'is_active':True,'needs_review':False,'source_kind':'manual','reference_count':0,'version':1}
        self.batches[batch]=payload_hash;self.audit(identity,actor,'equipment.created')

    def update_equipment(self, identity, equipment, values, actor):
        self.company(identity);e=self.equipment.get(str(equipment))
        if not e or e['company_id']!=str(identity):raise missing()
        if e['version']!=values['expected_version']:raise conflict()
        self.unique_equipment(identity,values['model_name'],values['serial_number'],str(equipment))
        e.update({k:v for k,v in values.items() if k!='expected_version'});e['version']+=1
        if e['is_confirmed']:e['needs_review']=False
        self.audit(identity,actor,'equipment.updated')


def registry(seed=None):return RegistryService(MemoryRegistry(seed),demo=True)

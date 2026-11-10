import hashlib
import json

from app.auth.service import AuthError
from app.customer_access.core import company_code, email_address


class RegistryError(AuthError):
    def __init__(self, code='REGISTRY_INVALID', message='입력값을 확인해 주세요.', status=400):
        self.code, self.status_code = code, status
        super().__init__(message)


def conflict():
    return RegistryError('REGISTRY_CONFLICT', '다른 작업에서 변경되었습니다. 최신 정보를 불러온 후 다시 시도해 주세요.', 409)


def missing():
    return RegistryError('REGISTRY_NOT_FOUND', '대상을 찾을 수 없습니다.', 404)


def text(value, limit=120, optional=False):
    value = (value or '').strip()
    if not value and optional:
        return None
    if not value or len(value)>limit or any(ord(c)<32 for c in value):
        raise RegistryError()
    return value


class RegistryService:
    def __init__(self, repository, demo=False):
        self.repository, self.demo = repository, demo

    def list(self, search, page):
        with self.repository.transaction() as work:
            return work.list_companies(search.strip(), page)

    def detail(self, identity, page=1):
        with self.repository.transaction() as work:
            return work.detail(identity, page)

    def create_company(self, code, name, actor):
        with self.repository.transaction() as work:
            return work.create_company(company_code(code), text(name), actor)

    def update_company(self, identity, name, active, version, actor):
        with self.repository.transaction() as work:
            work.update_company(identity, text(name), active, version, actor)
            return work.detail(identity, 1)

    def add_contact(self, identity, email, confirmed, actor):
        if not confirmed:
            raise RegistryError(message='해당 회사의 등록 이메일임을 확인해 주세요.')
        email = email_address(email)
        with self.repository.transaction() as work:
            work.add_contact(identity, email, actor)
            return work.detail(identity, 1)

    def contact_state(self, identity, contact, active, version, actor):
        with self.repository.transaction() as work:
            work.contact_state(identity, contact, active, version, actor)
            return work.detail(identity, 1)

    def add_equipment(self, identity, values, actor):
        values = dict(values)
        values['model_name'] = text(values['model_name'])
        values['serial_number'] = text(values.get('serial_number'), optional=True)
        values['manufacturing_site'] = text(values.get('manufacturing_site'), optional=True)
        if type(values['quantity']) is not int or not 1 <= values['quantity'] <= 100:
            raise RegistryError(message='등록 대수는 1~100대로 입력해 주세요.')
        if values['serial_number'] and values['quantity']!=1:
            raise RegistryError(message='호기를 입력하면 한 대씩 등록해 주세요.')
        key = values.pop('request_id')
        payload_hash = hashlib.sha256(json.dumps(values,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        with self.repository.transaction() as work:
            work.add_equipment(identity, key, payload_hash, values, actor)
            return work.detail(identity, 1)

    def update_equipment(self, identity, equipment, values, actor):
        values = dict(values)
        for key in ('model_name','serial_number','manufacturing_site'):
            values[key]=text(values.get(key), optional=key!='model_name')
        with self.repository.transaction() as work:
            work.update_equipment(identity,equipment,values,actor)
            return work.detail(identity,1)

import os
from uuid import UUID

from fastapi import APIRouter,Depends,Query,Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel,ConfigDict,Field,StrictBool,StrictInt
import psycopg

from app.auth.deps import require_operator,require_operator_csrf,check_origin
from app.auth.service import AuthError,BadOrigin,SessionInfo
from app.company_admin.core import RegistryError,RegistryService
from app.company_admin.store import RegistryRepository


class SafeRoute(APIRoute):
    def get_route_handler(self):
        handler=super().get_route_handler()
        async def safe(request):
            try:response=await handler(request)
            except RequestValidationError:
                response=JSONResponse({'code':'REGISTRY_INVALID','detail':'입력값의 형식과 길이를 확인해 주세요.'},status_code=422)
            except psycopg.errors.UniqueViolation:
                response=JSONResponse({'code':'REGISTRY_DUPLICATE','detail':'이미 등록된 회사코드·이메일·호기입니다. 기존 항목을 확인해 주세요.'},status_code=409)
            except psycopg.Error:
                response=JSONResponse({'code':'REGISTRY_UNAVAILABLE','detail':'관리 데이터를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.'},status_code=503)
            except AuthError as error:
                response=JSONResponse({'code':error.code,'detail':error.message},status_code=error.status_code)
            response.headers['Cache-Control']='no-store, private';response.headers['Vary']='Cookie'
            return response
        return safe


router=APIRouter(prefix='/api/v1/companies',tags=['company-registry'],route_class=SafeRoute)


def configured_service():
    if os.getenv('COMPANY_ADMIN_ENABLED')!='1' or os.getenv('APP_COOKIE_SECURE')!='1':return None
    dsn=os.getenv('DATABASE_URL','').strip()
    if not dsn:return None
    repo=RegistryRepository(dsn)
    return RegistryService(repo) if repo.ready() else None


def service(value=Depends(configured_service)):
    if value is None:raise RegistryError('REGISTRY_UNAVAILABLE','고객사 관리 데이터를 준비 중입니다.',503)
    return value


def write_session(request:Request,session:SessionInfo=Depends(require_operator_csrf)):
    check_origin(request)
    if not request.headers.get('origin'):raise BadOrigin()
    return session


def actor(session):return session.user.id,session.user.login_id


class Body(BaseModel):model_config=ConfigDict(extra='forbid')
class NewCompany(Body):
    code:str=Field(min_length=3,max_length=24)
    name:str=Field(min_length=1,max_length=120)
class CompanyUpdate(Body):
    name:str=Field(min_length=1,max_length=120)
    is_active:StrictBool
    expected_version:StrictInt=Field(ge=1)
class NewContact(Body):
    email:str=Field(min_length=3,max_length=254)
    confirmed:StrictBool
class ContactUpdate(Body):
    is_active:StrictBool
    expected_version:StrictInt=Field(ge=1)
class EquipmentFields(Body):
    model_name:str=Field(min_length=1,max_length=120)
    serial_number:str|None=Field(default=None,max_length=120)
    manufacturing_site:str|None=Field(default=None,max_length=120)
    is_confirmed:StrictBool
class NewEquipment(EquipmentFields):
    quantity:StrictInt=Field(ge=1,le=100)
    request_id:UUID
class EquipmentUpdate(EquipmentFields):
    is_active:StrictBool
    expected_version:StrictInt=Field(ge=1)


@router.get('/status')
def status(_session=Depends(require_operator),value=Depends(configured_service)):
    return {'available':value is not None,'demo':bool(value and value.demo)}


@router.get('')
def listing(_session=Depends(require_operator),value=Depends(service),search:str=Query('',max_length=120),page:int=Query(1,ge=1,le=100000)):
    return value.list(search,page)


@router.get('/{identity}')
def detail(identity:UUID,_session=Depends(require_operator),value=Depends(service),page:int=Query(1,ge=1,le=100000)):
    return value.detail(identity,page)


@router.post('',status_code=201)
def create(body:NewCompany,session=Depends(write_session),value=Depends(service)):
    return value.create_company(body.code,body.name,actor(session))


@router.put('/{identity}')
def update(identity:UUID,body:CompanyUpdate,session=Depends(write_session),value=Depends(service)):
    return value.update_company(identity,body.name,body.is_active,body.expected_version,actor(session))


@router.post('/{identity}/contacts',status_code=201)
def contact(identity:UUID,body:NewContact,session=Depends(write_session),value=Depends(service)):
    return value.add_contact(identity,body.email,body.confirmed,actor(session))


@router.put('/{identity}/contacts/{contact_id}')
def contact_state(identity:UUID,contact_id:UUID,body:ContactUpdate,session=Depends(write_session),value=Depends(service)):
    return value.contact_state(identity,contact_id,body.is_active,body.expected_version,actor(session))


@router.post('/{identity}/equipment',status_code=201)
def equipment(identity:UUID,body:NewEquipment,session=Depends(write_session),value=Depends(service)):
    return value.add_equipment(identity,body.model_dump(),actor(session))


@router.put('/{identity}/equipment/{equipment_id}')
def equipment_update(identity:UUID,equipment_id:UUID,body:EquipmentUpdate,session=Depends(write_session),value=Depends(service)):
    return value.update_equipment(identity,equipment_id,body.model_dump(),actor(session))

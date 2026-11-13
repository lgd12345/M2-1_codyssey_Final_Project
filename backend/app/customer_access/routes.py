import os

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
import psycopg

from app.auth.deps import check_origin, require_user
from app.auth.service import AuthError, SessionInfo
from app.customer_access.core import AccessError, AccessService, Settings, unavailable
from app.customer_access.mailer import deliver
from app.customer_access.store import PostgresRepository

CHALLENGE_COOKIES = {'register': 'claim_register_challenge', 'guest': 'claim_guest_challenge'}
GUEST_COOKIE = 'claim_guest_session'


class SafeRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe(request):
            try:
                response = await handler(request)
            except RequestValidationError:
                # Never reflect passwords, codes or arbitrary request bodies.
                response = JSONResponse({'code': 'ACCESS_INVALID', 'detail': '입력값의 형식과 길이를 확인해 주세요.'}, status_code=422)
            except psycopg.Error:
                error = unavailable()
                response = JSONResponse({'code': error.code, 'detail': error.message}, status_code=503)
            except AuthError as error:
                response = JSONResponse({'code': error.code, 'detail': error.message}, status_code=error.status_code)
            response.headers['Cache-Control'] = 'no-store, private'
            response.headers['Vary'] = 'Cookie'
            return response
        return safe


router = APIRouter(prefix='/api/v1/access', tags=['customer-access'], route_class=SafeRoute)


class PolicyConsent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    policy_version: str = Field(min_length=1, max_length=120)
    consent: StrictBool


class Start(PolicyConsent):
    purpose: str = Field(pattern='^(register|guest)$')
    company_code: str = Field(min_length=3, max_length=24)
    email: str = Field(min_length=3, max_length=254)


class Verify(PolicyConsent):
    code: str = Field(max_length=64)


class Register(Verify):
    password: str = Field(min_length=12, max_length=256)


class Inquiry(PolicyConsent):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=4000)

    @field_validator('title', 'body')
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError('empty')
        return value.strip()


def configured_service():
    settings = Settings.load(os.environ)
    if settings is None:
        return None
    repository = PostgresRepository(settings.database_url)
    return AccessService(settings, repository) if repository.ready(settings.registration) else None


def service(value=Depends(configured_service)):
    if value is None:
        raise unavailable()
    return value


def same_origin(request: Request):
    check_origin(request)
    if not request.headers.get('origin'):
        raise AccessError('BAD_ORIGIN', '허용되지 않은 요청 출처입니다.', 403)


def cookie(response, name, value, seconds):
    response.set_cookie(name, value, max_age=seconds, secure=True, httponly=True, samesite='strict', path='/api/v1/access')


@router.get('/status')
def status(response: Response, value=Depends(configured_service)):
    response.headers['Cache-Control'] = 'no-store, private'
    return {'available': value is not None, 'registration_available': bool(value and value.settings.registration),
            'policy': value.settings.policy if value else None}


@router.get('/customer/profile')
def customer_profile(response: Response, session: SessionInfo = Depends(require_user), value=Depends(service)):
    if session.user.role != 'customer':
        raise AccessError('CUSTOMER_REQUIRED', '고객 계정으로 로그인해 주세요.', 403)
    with value.repository.transaction() as work:
        company = work.customer_profile(session.user.id)
        if company is None:
            raise AccessError('COMPANY_REQUIRED', '회사 소속을 확인할 수 없습니다.', 403)
    response.headers['Cache-Control'] = 'no-store, private'
    return {'company': company}


@router.post('/challenges', status_code=202, dependencies=[Depends(same_origin)])
def start(body: Start, request: Request, response: Response, tasks: BackgroundTasks, value=Depends(service)):
    proof, identity, recipient, number = value.start(body.purpose, body.company_code, body.email,
        request.client.host if request.client else 'unknown', body.policy_version, body.consent)
    cookie(response, CHALLENGE_COOKIES[body.purpose], proof, 600)
    response.headers['Cache-Control'] = 'no-store, private'
    if recipient:
        tasks.add_task(deliver, value, identity, recipient, number)
    return {'message': '인증번호 발송을 요청했습니다. 메일을 확인해 주세요.', 'expires_in': 600, 'retry_after': 60}


@router.post('/registration/verify', dependencies=[Depends(same_origin)])
def verify_registration(body: Verify, request: Request, response: Response, value=Depends(service)):
    result = value.verify_registration(request.cookies.get(CHALLENGE_COOKIES['register']), body.code,
                                       body.policy_version, body.consent)
    if result['state'] == 'already_registered':
        response.delete_cookie(CHALLENGE_COOKIES['register'], path='/api/v1/access', secure=True, httponly=True, samesite='strict')
    return result


@router.post('/registration', status_code=201, dependencies=[Depends(same_origin)])
def register(body: Register, request: Request, response: Response, value=Depends(service)):
    result = value.register(request.cookies.get(CHALLENGE_COOKIES['register']), body.code,
        body.password, body.policy_version, body.consent)
    response.delete_cookie(CHALLENGE_COOKIES['register'], path='/api/v1/access', secure=True, httponly=True, samesite='strict')
    response.headers['Cache-Control'] = 'no-store, private'
    return result


@router.post('/guest/session', dependencies=[Depends(same_origin)])
def guest(body: Verify, request: Request, response: Response, value=Depends(service)):
    token, result = value.guest(request.cookies.get(CHALLENGE_COOKIES['guest']), body.code, body.policy_version, body.consent)
    cookie(response, GUEST_COOKIE, token, 1800)
    response.delete_cookie(CHALLENGE_COOKIES['guest'], path='/api/v1/access', secure=True, httponly=True, samesite='strict')
    response.headers['Cache-Control'] = 'no-store, private'
    return result


@router.get('/guest/session')
def guest_state(request: Request, response: Response, value=Depends(service)):
    response.headers['Cache-Control'] = 'no-store, private'
    return value.guest_state(request.cookies.get(GUEST_COOKIE))


@router.get('/guest/inquiry')
def get_inquiry(request: Request, response: Response, value=Depends(service)):
    response.headers['Cache-Control'] = 'no-store, private'
    return {'inquiry': value.inquiry(request.cookies.get(GUEST_COOKIE))}


@router.post('/guest/inquiry', status_code=201, dependencies=[Depends(same_origin)])
def put_inquiry(body: Inquiry, request: Request, response: Response, value=Depends(service)):
    response.headers['Cache-Control'] = 'no-store, private'
    result = value.inquiry(request.cookies.get(GUEST_COOKIE), body.title, body.body,
                           request.headers.get('x-csrf-token'), body.policy_version, body.consent)
    return {'inquiry': result}

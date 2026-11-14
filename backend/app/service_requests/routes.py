"""Authenticated intake/list/detail; the server owns identity, time and IDs."""
import asyncio
import logging
from contextlib import contextmanager
from typing import Literal
from uuid import UUID
import re

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.auth.deps import database, require_user, require_csrf, require_operator_csrf
from app.auth.service import AuthError, SessionInfo
from app.service_requests import analysis as analysis_flow
from app.service_requests import views

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api/v1/service-requests', tags=['service-requests'])


class CompanyRequired(AuthError):
    status_code, code = 403, 'COMPANY_REQUIRED'
    message = '고객사 소속이 등록되지 않았습니다. 관리자에게 문의해 주세요.'


class RequestNotFound(AuthError):
    status_code, code = 404, 'REQUEST_NOT_FOUND'
    message = '요청 또는 장비를 찾을 수 없습니다.'


class RequestsNotReady(AuthError):
    status_code, code = 503, 'REQUESTS_NOT_READY'
    message = '요청 저장소가 준비되지 않았습니다. 관리자에게 문의해 주세요.'


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Contact(Input):
    name: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=1, max_length=40)
    email: EmailStr | None = None

    @field_validator('email', mode='before')
    @classmethod
    def empty_email(cls, value):
        return None if isinstance(value, str) and not value.strip() else value


class Intake(Input):
    equipment_id: UUID
    reason: Literal['기계 고장', '기술 문의', '부품 문의', '교육·기술지원']
    message: str = Field(min_length=1, max_length=10000)
    alarm_numbers: list[str] = Field(default_factory=list, max_length=20)
    contact: Contact

    @field_validator('alarm_numbers')
    @classmethod
    def alarms(cls, values):
        if any(len(value.strip()) > 80 for value in values):
            raise ValueError('alarm number too long')
        return [value.strip() for value in values if value.strip()]


@contextmanager
def request_database():
    try:
        with database() as connection:
            yield connection
    except psycopg.errors.UndefinedTable:
        # Deliberately do not create tables at startup or fall back to demo data.
        raise RequestsNotReady() from None


def membership(connection, session):
    with connection.cursor(row_factory=dict_row) as cursor:
        return cursor.execute('''SELECT c.id, c.name FROM service_company c
            JOIN service_company_member m ON m.company_id=c.id WHERE m.user_id=%s''',
                              (session.user.id,)).fetchone()


def access_company(connection, session):
    if session.user.role == 'admin':
        return None
    company = membership(connection, session)
    if not company:
        raise CompanyRequired()
    return company['id']


@router.get('/context')
def context(session: SessionInfo = Depends(require_user)):
    with request_database() as connection:
        company = membership(connection, session) if session.user.role != 'admin' else None
        if not company and session.user.role != 'admin':
            return {'company': None, 'equipment': [], 'can_submit': False}
        with connection.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute('''SELECT e.id, e.machine, e.serial, c.name AS company
                FROM service_equipment e JOIN service_company c ON c.id=e.company_id
                WHERE (%s OR e.company_id=%s) ORDER BY c.name,e.machine,e.serial''',
                                  (session.user.role == 'admin', company['id'] if company else None)).fetchall()
        return {'company': company, 'equipment': rows, 'can_submit': bool(rows)}


@router.post('', status_code=201)
def create(body: Intake, session: SessionInfo = Depends(require_csrf)):
    with request_database() as connection:
        company_id = access_company(connection, session)
        with connection.cursor(row_factory=dict_row) as cursor:
            equipment = cursor.execute('''SELECT e.id,e.company_id,e.machine,e.serial,c.name AS company
                FROM service_equipment e JOIN service_company c ON c.id=e.company_id
                WHERE e.id=%s AND (%s OR e.company_id=%s) FOR SHARE OF e,c''',
                                       (body.equipment_id, session.user.role == 'admin', company_id)).fetchone()
            if not equipment:
                raise RequestNotFound()
            snapshot = {key: equipment[key] for key in ('company', 'machine', 'serial')}
            row = cursor.execute('''INSERT INTO service_request
                (equipment_id,company_id,created_by,title,reason,message,alarm_numbers,contact,equipment_snapshot)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
                                 (equipment['id'], equipment['company_id'], session.user.id, body.message[:80],
                                  body.reason, body.message, Jsonb(body.alarm_numbers),
                                  Jsonb(body.contact.model_dump(mode='json')), Jsonb(snapshot))).fetchone()
        return views.fetch_items(connection, 'r.id=%s', (row['id'],), staff=session.user.role == 'admin')[0]


@router.get('')
def list_requests(session: SessionInfo = Depends(require_user)):
    with request_database() as connection:
        analysis_flow.recover_orphans(connection)
        company_id = access_company(connection, session)
        items = views.fetch_items(connection, '(%s OR r.company_id=%s)', (session.user.role == 'admin', company_id),
                                  staff=session.user.role == 'admin', order='ORDER BY r.created_at DESC,r.id DESC')
        return {'requests': items}


def request_number(identity: str) -> int:
    if not re.fullmatch(r'CLM-[0-9]{3,19}', identity):
        raise RequestNotFound()
    number = int(identity[4:])
    if number < 1 or number > 9223372036854775807:
        raise RequestNotFound()
    return number


@router.get('/{identity}')
def detail(identity: str, session: SessionInfo = Depends(require_user)):
    number = request_number(identity)
    with request_database() as connection:
        analysis_flow.recover_orphans(connection)
        company_id = access_company(connection, session)
        found = views.fetch_items(connection, 'r.id=%s AND (%s OR r.company_id=%s)',
                                  (number, session.user.role == 'admin', company_id), staff=session.user.role == 'admin')
        if not found:
            raise RequestNotFound()
        return found[0]


class NoBody(Input):
    pass


def _write(action, *args) -> None:
    with request_database() as connection:
        action(connection, *args)


async def execute_analysis(analysis_id, request_input, runner) -> None:
    try:
        result = analysis_flow.validate_result(await runner(request_input))
    except asyncio.CancelledError:
        await asyncio.shield(asyncio.to_thread(_write, analysis_flow.finish_failure, analysis_id, 'interrupted'))
        raise
    except Exception as error:
        # Never the message of unknown errors: it may hold secrets. Our own grounding errors are fixed text.
        detail = f': {error}' if isinstance(error, analysis_flow.InvalidAnalysis) else ''
        logger.warning('analysis failed: %s%s', type(error).__name__, detail)
        await asyncio.to_thread(_write, analysis_flow.finish_failure, analysis_id, analysis_flow.error_code_for(error))
        return
    try:
        await asyncio.to_thread(_write, analysis_flow.finish_success, analysis_id, result)
    except Exception as error:
        logger.warning('analysis result could not be stored: %s', type(error).__name__)
        await asyncio.to_thread(_write, analysis_flow.finish_failure, analysis_id, 'storage_error')


@router.post('/{identity}/analysis', status_code=202)
def start_analysis(identity: str, background: BackgroundTasks, body: NoBody | None = None,
                   session: SessionInfo = Depends(require_operator_csrf),
                   runner: analysis_flow.AnalysisRunner = Depends(analysis_flow.get_analysis_runner)):
    number = request_number(identity)
    with request_database() as connection:
        analysis_id, request_input = analysis_flow.begin(connection, number, session.user.id)
    background.add_task(execute_analysis, analysis_id, request_input, runner)
    return {'id': identity, 'status': '분석 중'}

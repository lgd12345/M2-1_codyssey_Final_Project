"""HTTP surface of the request workflow. Operator actions need admin; customer actions need a company member."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import ConfigDict, Field, StrictBool, model_validator

from app.auth.deps import require_csrf, require_operator_csrf
from app.auth.service import AuthError, SessionInfo
from app.service_requests import analysis as analysis_flow
from app.service_requests import views, workflow
from app.service_requests.routes import (
    Input, NoBody, access_company, execute_analysis, request_database, request_number,
)

router = APIRouter(prefix='/api/v1/service-requests', tags=['service-requests-workflow'])
DepartmentKey = Literal['service', 'quality', 'parts', 'sales']


class CustomerRequired(AuthError):
    status_code, code = 403, 'CUSTOMER_REQUIRED'
    message = '고객 계정만 이용할 수 있는 기능입니다.'


def require_customer_csrf(session: SessionInfo = Depends(require_csrf)) -> SessionInfo:
    if session.user.role == 'admin':
        raise CustomerRequired()
    return session


class DepartmentEdit(Input):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    selected: StrictBool | None = None
    draft: str | None = Field(default=None, max_length=10000)
    reset: Literal[True] | None = None

    @model_validator(mode='after')
    def exactly_one_kind_of_change(self):
        given = [name for name in ('selected', 'draft', 'reset') if getattr(self, name) is not None]
        if not given or (self.reset and len(given) > 1):
            raise ValueError('send selected, draft or reset')
        return self


class CommentIn(Input):
    kind: Literal['internal', 'public']
    text: str = Field(min_length=1, max_length=4000)


class DeclineIn(Input):
    reason: str = Field(min_length=1, max_length=2000)


class CompleteIn(Input):
    summary: str = Field(min_length=1, max_length=4000)
    hours: str = Field(default='', max_length=20)


class ResolveIn(Input):
    note: str = Field(default='', max_length=2000)


class ReplyIn(Input):
    text: str = Field(min_length=1, max_length=4000)


class CloseRequestIn(Input):
    reason: str = Field(min_length=1, max_length=2000)


def _operator_item(connection, number: int) -> dict:
    return views.fetch_items(connection, 'r.id=%s', (number,), staff=True)[0]


def _customer_item(connection, number: int) -> dict:
    return views.fetch_items(connection, 'r.id=%s', (number,), staff=False)[0]


@router.patch('/{identity}/departments/{key}')
def edit_department(identity: str, key: DepartmentKey, body: DepartmentEdit,
                    session: SessionInfo = Depends(require_operator_csrf)):
    number = request_number(identity)
    with request_database() as connection:
        workflow.edit_department(connection, number, key, body.model_dump(exclude_none=True))
        return _operator_item(connection, number)


@router.post('/{identity}/assignee')
def assign(identity: str, body: NoBody | None = None, session: SessionInfo = Depends(require_operator_csrf)):
    number = request_number(identity)
    with request_database() as connection:
        workflow.assign(connection, number, session.user)
        return _operator_item(connection, number)


@router.post('/{identity}/comments', status_code=201)
def add_comment(identity: str, body: CommentIn, session: SessionInfo = Depends(require_operator_csrf)):
    number = request_number(identity)
    with request_database() as connection:
        workflow.comment(connection, number, session.user, body.kind, body.text)
        return _operator_item(connection, number)


@router.post('/{identity}/approval')
def approve(identity: str, body: NoBody | None = None, session: SessionInfo = Depends(require_operator_csrf)):
    number = request_number(identity)
    with request_database() as connection:
        workflow.approve(connection, number, session.user)
        return _operator_item(connection, number)


@router.post('/{identity}/decline')
def decline(identity: str, body: DeclineIn, session: SessionInfo = Depends(require_operator_csrf)):
    number = request_number(identity)
    with request_database() as connection:
        workflow.decline(connection, number, session.user, body.reason)
        return _operator_item(connection, number)


@router.post('/{identity}/reanalysis', status_code=202)
def reanalyze(identity: str, background: BackgroundTasks, body: NoBody | None = None,
              session: SessionInfo = Depends(require_operator_csrf),
              runner: analysis_flow.AnalysisRunner = Depends(analysis_flow.get_analysis_runner)):
    number = request_number(identity)
    with request_database() as connection:
        analysis_id, request_input = analysis_flow.begin(
            connection, number, session.user.id, allowed=workflow.REANALYZABLE, history='재분석 요청')
    background.add_task(execute_analysis, analysis_id, request_input, runner)
    return {'id': identity, 'status': '분석 중'}


@router.post('/{identity}/work/{work_key}/assignee')
def work_assign(identity: str, work_key: str, body: NoBody | None = None,
                session: SessionInfo = Depends(require_operator_csrf)):
    number = request_number(identity)
    with request_database() as connection:
        workflow.work_assign(connection, number, work_key, session.user)
        return _operator_item(connection, number)


@router.post('/{identity}/work/{work_key}/start')
def work_start(identity: str, work_key: str, body: NoBody | None = None,
               session: SessionInfo = Depends(require_operator_csrf)):
    number = request_number(identity)
    with request_database() as connection:
        workflow.work_start(connection, number, work_key, session.user)
        return _operator_item(connection, number)


@router.post('/{identity}/work/{work_key}/complete')
def work_complete(identity: str, work_key: str, body: CompleteIn, session: SessionInfo = Depends(require_operator_csrf)):
    number = request_number(identity)
    with request_database() as connection:
        workflow.work_complete(connection, number, work_key, session.user, body.summary, body.hours)
        return _operator_item(connection, number)


@router.post('/{identity}/resolution')
def resolve(identity: str, body: ResolveIn | None = None, session: SessionInfo = Depends(require_operator_csrf)):
    number = request_number(identity)
    with request_database() as connection:
        workflow.resolve(connection, number, session.user, (body.note if body else '').strip())
        return _operator_item(connection, number)


# ----- customer actions -----

@router.post('/{identity}/replies', status_code=201)
def reply(identity: str, body: ReplyIn, background: BackgroundTasks,
          session: SessionInfo = Depends(require_customer_csrf),
          runner: analysis_flow.AnalysisRunner = Depends(analysis_flow.get_analysis_runner)):
    number = request_number(identity)
    with request_database() as connection:
        company_id = access_company(connection, session)
        reanalyze_now = workflow.customer_reply(connection, number, session.user, company_id, body.text)
        if reanalyze_now:
            analysis_id, request_input = analysis_flow.begin(
                connection, number, session.user.id, allowed=('추가 정보 필요',), history='고객 답변 · 재분석')
            background.add_task(execute_analysis, analysis_id, request_input, runner)
        return _customer_item(connection, number)


@router.post('/{identity}/callback', status_code=201)
def callback(identity: str, body: NoBody | None = None, session: SessionInfo = Depends(require_customer_csrf)):
    number = request_number(identity)
    with request_database() as connection:
        workflow.customer_callback(connection, number, session.user, access_company(connection, session))
        return _customer_item(connection, number)


@router.post('/{identity}/close-request', status_code=201)
def close_request(identity: str, body: CloseRequestIn, session: SessionInfo = Depends(require_customer_csrf)):
    number = request_number(identity)
    with request_database() as connection:
        workflow.customer_close_request(connection, number, session.user, access_company(connection, session), body.reason)
        return _customer_item(connection, number)

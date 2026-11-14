"""HTTP surface of the request workflow. Every action here is an operator action (admin, session and CSRF).

Customers file a request and follow its progress; they have no actions after filing."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import ConfigDict, Field, StrictBool, model_validator

from app.auth.deps import require_operator_csrf
from app.auth.service import SessionInfo
from app.service_requests import analysis as analysis_flow
from app.service_requests import views, workflow
from app.service_requests.routes import (
    Input, NoBody, execute_analysis, request_database, request_number,
)

router = APIRouter(prefix='/api/v1/service-requests', tags=['service-requests-workflow'])
DepartmentKey = Literal['service', 'quality', 'parts', 'sales']


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


class AdditionalInfoIn(Input):
    text: str = Field(min_length=1, max_length=2000)


class DeclineIn(Input):
    reason: str = Field(min_length=1, max_length=2000)


class CompleteIn(Input):
    summary: str = Field(min_length=1, max_length=4000)
    hours: str = Field(default='', max_length=20)


class ResolveIn(Input):
    note: str = Field(default='', max_length=2000)


def _operator_item(connection, number: int) -> dict:
    return views.fetch_items(connection, 'r.id=%s', (number,), staff=True)[0]


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


@router.post('/{identity}/additional-info', status_code=201)
def add_additional_info(identity: str, body: AdditionalInfoIn, session: SessionInfo = Depends(require_operator_csrf)):
    number = request_number(identity)
    with request_database() as connection:
        workflow.add_additional_info(connection, number, session.user, body.text)
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

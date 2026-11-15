"""HTTP surface of the request workflow. Every action here is an operator action (admin, session and CSRF).

Customers file a request and follow its progress; they have no actions after filing."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import Field

from app.auth.deps import require_operator_csrf
from app.auth.service import SessionInfo
from app.mail.deps import get_mail_sender
from app.service_requests import analysis as analysis_flow
from app.service_requests import views, workflow
from app.service_requests.routes import (
    Input, NoBody, execute_analysis, queue_mail, request_database, request_number,
)
from typing import Literal

router = APIRouter(prefix='/api/v1/service-requests', tags=['service-requests-workflow'])


class CommentIn(Input):
    kind: Literal['internal', 'public']
    text: str = Field(min_length=1, max_length=4000)


class AdditionalInfoIn(Input):
    text: str = Field(min_length=1, max_length=2000)


class ResolveIn(Input):
    note: str = Field(min_length=1, max_length=2000)  # the processing result: the customer's guide page and completion mail


def _operator_item(connection, number: int) -> dict:
    return views.fetch_items(connection, 'r.id=%s', (number,), staff=True)[0]


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


@router.post('/{identity}/reanalysis', status_code=202)
def reanalyze(identity: str, background: BackgroundTasks, body: NoBody | None = None,
              session: SessionInfo = Depends(require_operator_csrf),
              runner: analysis_flow.AnalysisRunner = Depends(analysis_flow.get_analysis_runner)):
    number = request_number(identity)
    with request_database() as connection:
        analysis_id, request_input, _ = analysis_flow.begin(
            connection, number, session.user.id, first=False, history='재분석 요청')
    background.add_task(execute_analysis, analysis_id, request_input, runner)
    return {'id': identity, 'status': '처리 중'}


@router.post('/{identity}/resolution')
def resolve(identity: str, body: ResolveIn, background: BackgroundTasks,
            session: SessionInfo = Depends(require_operator_csrf), sender=Depends(get_mail_sender)):
    number = request_number(identity)
    with request_database() as connection:
        workflow.resolve(connection, number, session.user, body.note.strip())
        queue_mail(connection, background, sender, number, 'resolved')
        return _operator_item(connection, number)

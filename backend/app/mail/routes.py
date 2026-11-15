"""Operator-only: department list, mail drafts, and the send/cancel buttons. Registered before the request routes."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends
from pydantic import Field

from app.auth.deps import require_operator, require_operator_csrf
from app.auth.service import SessionInfo
from app.mail import drafts
from app.mail.deps import get_mail_sender
from app.service_requests import views
from app.service_requests.routes import Input, request_database, request_number

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api/v1/service-requests', tags=['service-mail'])


class DraftIn(Input):
    department_key: str = Field(min_length=1, max_length=31)
    subject: str = Field(min_length=1, max_length=150)
    body: str = Field(min_length=1, max_length=4000)


class SendIn(Input):
    subject: str | None = Field(default=None, max_length=150)
    body: str | None = Field(default=None, max_length=4000)


class Empty(Input):
    pass


def _item(connection, number: int) -> dict:
    return views.fetch_items(connection, 'r.id=%s', (number,), staff=True)[0]


@router.get('/departments')
def list_departments(session: SessionInfo = Depends(require_operator)):
    with request_database() as connection:
        return {'departments': drafts.departments(connection)}


@router.post('/{identity}/mail-drafts', status_code=201)
def create_draft(identity: str, body: DraftIn, session: SessionInfo = Depends(require_operator_csrf)):
    number = request_number(identity)
    with request_database() as connection:
        draft_id = drafts.create(connection, number, body.department_key, body.subject, body.body, session.user.id)
        return {'id': draft_id, 'item': _item(connection, number)}


@router.post('/{identity}/mail-drafts/{draft_id}/send')
async def send_draft(identity: str, draft_id: int, body: SendIn | None = None,
                     session: SessionInfo = Depends(require_operator_csrf), sender=Depends(get_mail_sender)):
    number = request_number(identity)
    if sender is None:
        raise drafts.MailOff()

    def claim():
        with request_database() as connection:
            return drafts.claim(connection, number, draft_id, body.model_dump() if body else {})

    def finish(name: str, ok: bool):
        with request_database() as connection:
            drafts.finish(connection, number, draft_id, name, session.user.login_id, ok)
            return _item(connection, number)

    claimed = await asyncio.to_thread(claim)
    try:
        await drafts.send(sender, claimed)
    except Exception as error:  # noqa: BLE001 - a fixed code only; the transport's text can hold addresses or credentials
        logger.warning('department mail failed: %s', type(error).__name__)
        await asyncio.to_thread(finish, claimed['name'], False)
        raise drafts.MailFailed() from None
    view = await asyncio.to_thread(finish, claimed['name'], True)
    return {'id': draft_id, 'status': 'sent', 'item': view}


@router.post('/{identity}/mail-drafts/{draft_id}/cancel')
def cancel_draft(identity: str, draft_id: int, body: Empty | None = None, session: SessionInfo = Depends(require_operator_csrf)):
    number = request_number(identity)
    with request_database() as connection:
        drafts.cancel(connection, number, draft_id)
        return {'id': draft_id, 'status': 'cancelled', 'item': _item(connection, number)}

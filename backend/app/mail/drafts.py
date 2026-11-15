"""Department mail drafts. Drafting never sends. Sending happens only through send(), which the button API calls.

Recipient addresses come from the service_department table by department key; neither the model nor the browser supplies one.
"""
from __future__ import annotations

import re
from typing import Any

from psycopg.rows import dict_row

from app.auth.service import AuthError
from app.mail.smtp import build_message
from app.service_requests.analysis import add_history

WORKER_ID = re.compile(r'EMP-\d{3,}')  # pseudonymised worker IDs stay on the operator screen


class InvalidDraft(AuthError):
    status_code, code = 422, 'INVALID_MAIL_DRAFT'
    message = '메일 내용을 확인해 주세요. 제목은 한 줄 150자 이하, 본문은 4000자 이하이며 작업자 ID는 넣을 수 없습니다.'


class DraftNotFound(AuthError):
    status_code, code = 404, 'MAIL_DRAFT_NOT_FOUND'
    message = '메일 초안을 찾을 수 없습니다.'


class DraftNotSendable(AuthError):
    status_code, code = 409, 'MAIL_DRAFT_STATE'
    message = '이미 보냈거나 취소된 메일입니다.'


class NoRecipient(AuthError):
    status_code, code = 409, 'NO_RECIPIENT'
    message = '이 부서에 등록된 수신 주소가 없습니다.'


class MailOff(AuthError):
    status_code, code = 503, 'MAIL_OFF'
    message = '메일 발송이 설정되지 않았습니다. 관리자에게 문의해 주세요.'


class DepartmentNotFound(AuthError):
    status_code, code = 404, 'DEPARTMENT_NOT_FOUND'
    message = '부서를 찾을 수 없습니다.'


class DepartmentExists(AuthError):
    status_code, code = 409, 'DEPARTMENT_EXISTS'
    message = '같은 키의 부서가 이미 있습니다.'


class MailAiInvalid(AuthError):
    status_code, code = 502, 'MAIL_AI_INVALID'
    message = 'AI가 만든 초안이 메일 규칙에 맞지 않았습니다. 다시 시도하거나 직접 작성해 주세요.'


class MailAiFailed(AuthError):
    status_code, code = 502, 'MAIL_AI_FAILED'
    message = 'AI가 초안을 만들지 못했습니다. 직접 작성해 주세요.'


class MailFailed(AuthError):
    status_code, code = 502, 'MAIL_FAILED'
    message = '메일을 보내지 못했습니다. 잠시 후 다시 시도해 주세요.'


def clean(subject: str, body: str) -> tuple[str, str]:
    subject, body = (subject or '').strip(), (body or '').strip()
    if (not subject or len(subject) > 150 or re.search(r'[\r\n]', subject) or not body or len(body) > 4000
            or WORKER_ID.search(subject) or WORKER_ID.search(body)):
        raise InvalidDraft()
    return subject, body


def departments(connection, *, active_only: bool = True) -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute('SELECT key,name,description,cardinality(recipients) > 0 AS has FROM service_department '
                              + ('WHERE active ' if active_only else '') + 'ORDER BY key').fetchall()
    return [{'key': r['key'], 'name': r['name'], 'description': r['description'], 'hasRecipient': r['has']} for r in rows]


def create(connection, number: int, department_key: str, subject: str, body: str, author_id) -> int:
    subject, body = clean(subject, body)
    row = connection.execute('SELECT 1 FROM service_request WHERE id=%s', (number,)).fetchone()
    if row is None:
        from app.service_requests.routes import RequestNotFound
        raise RequestNotFound()
    dept = connection.execute('SELECT active, cardinality(recipients) FROM service_department WHERE key=%s',
                              (department_key,)).fetchone()
    if not dept or not dept[0] or not dept[1]:
        raise InvalidDraft('이 부서는 메일을 받을 수 없습니다. 부서와 수신 주소 등록을 확인해 주세요.')
    return connection.execute(
        'INSERT INTO service_mail_draft(request_id,department_key,subject,body,created_by) VALUES (%s,%s,%s,%s,%s) RETURNING id',
        (number, department_key, subject, body, author_id)).fetchone()[0]


def claim(connection, number: int, draft_id: int, edited: dict[str, str | None]) -> dict[str, Any]:
    """Draft or failed -> sending, in one transaction. Applies the operator's edits from the card."""
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute('SELECT * FROM service_mail_draft WHERE id=%s AND request_id=%s FOR UPDATE',
                             (draft_id, number)).fetchone()
        if row is None:
            raise DraftNotFound()
        if row['status'] not in ('draft', 'failed'):
            raise DraftNotSendable()
        subject, body = clean(edited.get('subject') or row['subject'], edited.get('body') or row['body'])
        dept = cursor.execute('SELECT name, recipients, active FROM service_department WHERE key=%s',
                              (row['department_key'],)).fetchone()
        if not dept['active'] or not dept['recipients']:
            raise NoRecipient()
        cursor.execute("UPDATE service_mail_draft SET status='sending', subject=%s, body=%s WHERE id=%s",
                       (subject, body, draft_id))
    return {'subject': subject, 'body': body, 'recipients': list(dept['recipients']), 'name': dept['name']}


async def send(sender, claimed: dict[str, Any]) -> None:
    message = build_message(sender.from_address, ', '.join(claimed['recipients']), claimed['subject'], claimed['body'])
    await sender.send(message)


def finish(connection, number: int, draft_id: int, name: str, actor_login: str, ok: bool) -> None:
    if ok:
        connection.execute("UPDATE service_mail_draft SET status='sent', sent_by_login=%s, sent_at=now(), error_code=NULL WHERE id=%s",
                           (actor_login, draft_id))
        add_history(connection, number, f'메일 발송 · {name} · {actor_login}')  # internal only
    else:
        connection.execute("UPDATE service_mail_draft SET status='failed', error_code='send_failed' WHERE id=%s", (draft_id,))


def cancel(connection, number: int, draft_id: int) -> None:
    row = connection.execute('SELECT status FROM service_mail_draft WHERE id=%s AND request_id=%s FOR UPDATE',
                             (draft_id, number)).fetchone()
    if row is None:
        raise DraftNotFound()
    if row[0] not in ('draft', 'failed'):
        raise DraftNotSendable()
    connection.execute("UPDATE service_mail_draft SET status='cancelled' WHERE id=%s", (draft_id,))


def manage_list(connection) -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute("SELECT key,name,description,recipients,active,updated_by,updated_at FROM service_department "
            "ORDER BY array_position(ARRAY['service','quality','parts','sales'], key), key").fetchall()
    return [{'key': r['key'], 'name': r['name'], 'description': r['description'], 'recipients': list(r['recipients']),
             'active': r['active'], 'updatedBy': r['updated_by'], 'updatedAt': r['updated_at'].isoformat() if r['updated_at'] else None}
            for r in rows]


def add_department(connection, key: str, name: str, description: str, recipients: list[str], actor: str) -> None:
    import psycopg
    try:
        with connection.transaction():
            connection.execute(
                'INSERT INTO service_department(key,name,description,recipients,updated_by,updated_at) VALUES (%s,%s,%s,%s,%s,now())',
                (key, name.strip(), description.strip(), recipients, actor))
    except psycopg.errors.UniqueViolation:
        raise DepartmentExists() from None


def change_department(connection, key: str, change: dict[str, Any], actor: str) -> None:
    columns = {'name': 'name', 'description': 'description', 'recipients': 'recipients', 'active': 'active'}
    sets = [f'{columns[field]}=%s' for field in change]
    values = [value.strip() if isinstance(value, str) else value for value in change.values()]
    row = connection.execute(f'UPDATE service_department SET {", ".join(sets)}, updated_by=%s, updated_at=now() WHERE key=%s RETURNING key',
                             (*values, actor, key)).fetchone()
    if row is None:
        raise DepartmentNotFound()

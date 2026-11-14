"""State transitions for review, approval, department work, comments, customer actions and closure.

Every transition locks the request row first, so concurrent clicks cannot approve, start or close twice.
The server decides actors, times, IDs and work keys; clients only choose the action and its text.
"""
from __future__ import annotations

from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.auth.service import AuthError
from app.service_requests.analysis import add_history
from app.service_requests.views import DEPARTMENT_NAMES

EDITABLE = ('검토 대기', '추가 정보 필요')
REANALYZABLE = ('검토 대기', '추가 정보 필요', '반려됨')
PREFIX = {'service': 'SVC', 'quality': 'QLT', 'parts': 'PRT', 'sales': 'SAL'}


class InvalidState(AuthError):
    status_code, code = 409, 'INVALID_STATE'
    message = '현재 요청 상태에서는 할 수 없는 작업입니다.'


class ApprovalRequirements(AuthError):
    status_code, code = 409, 'APPROVAL_REQUIREMENTS'
    message = '부서를 한 곳 이상 선택하고 모든 초안을 채워야 승인할 수 있습니다.'


class WorkNotComplete(AuthError):
    status_code, code = 409, 'WORK_NOT_COMPLETE'
    message = '모든 연결 업무가 완료되어야 종결할 수 있습니다.'


class AlreadyAssigned(AuthError):
    status_code, code = 409, 'ALREADY_ASSIGNED'
    message = '이미 담당자가 지정되어 있습니다.'


class WorkNotFound(AuthError):
    status_code, code = 404, 'WORK_NOT_FOUND'
    message = '연결 업무를 찾을 수 없습니다.'


class NotFound(AuthError):
    status_code, code = 404, 'REQUEST_NOT_FOUND'
    message = '요청 또는 장비를 찾을 수 없습니다.'


def lock(connection, number: int) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute('SELECT * FROM service_request WHERE id=%s FOR UPDATE', (number,)).fetchone()
    if row is None:
        raise NotFound()
    return row


def _departments(connection, number: int) -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        return cursor.execute('SELECT * FROM service_request_department WHERE request_id=%s ORDER BY key', (number,)).fetchall()


def edit_department(connection, number: int, key: str, change: dict[str, Any]) -> None:
    row = lock(connection, number)
    if row['status'] not in EDITABLE or not _departments(connection, number):
        raise InvalidState()
    if change.get('reset'):
        connection.execute('UPDATE service_request_department SET draft=ai_draft WHERE request_id=%s AND key=%s', (number, key))
    if change.get('selected') is not None:
        connection.execute('UPDATE service_request_department SET selected=%s WHERE request_id=%s AND key=%s',
                           (change['selected'], number, key))
    if change.get('draft') is not None:
        connection.execute('UPDATE service_request_department SET draft=%s WHERE request_id=%s AND key=%s',
                           (change['draft'], number, key))


def assign(connection, number: int, actor) -> None:
    row = lock(connection, number)
    if row['assignee'] == actor.login_id:
        return
    if row['assignee']:
        raise AlreadyAssigned()
    connection.execute('UPDATE service_request SET assignee=%s WHERE id=%s', (actor.login_id, number))
    add_history(connection, number, f'{actor.login_id} 담당자로 지정')


def add_comment(connection, number: int, actor, kind: str, text: str) -> None:
    connection.execute('INSERT INTO service_comment(request_id,author_id,author,kind,text) VALUES (%s,%s,%s,%s,%s)',
                       (number, actor.id, actor.login_id, kind, text))


def comment(connection, number: int, actor, kind: str, text: str) -> None:
    lock(connection, number)
    add_comment(connection, number, actor, kind, text)


def add_additional_info(connection, number: int, actor, text: str) -> None:
    """Operator-entered facts from outside the app. Only while the request can still be analysed again."""
    row = lock(connection, number)
    if row['status'] not in REANALYZABLE:
        raise InvalidState()
    connection.execute('INSERT INTO service_additional_info(request_id,author_id,author,text) VALUES (%s,%s,%s,%s)',
                       (number, actor.id, actor.login_id, text))
    add_history(connection, number, f'추가 정보 입력 · {actor.login_id}')  # internal only: no public wording


def approve(connection, number: int, actor) -> None:
    row = lock(connection, number)
    departments = _departments(connection, number)
    if row['status'] not in EDITABLE or not departments:
        raise InvalidState()
    selected = [d for d in departments if d['selected']]
    if not selected or any(not d['draft'].strip() for d in selected):
        raise ApprovalRequirements()
    ordered = sorted(selected, key=lambda d: list(PREFIX).index(d['key']))
    delivered = [{'key': d['key'], 'name': DEPARTMENT_NAMES[d['key']], 'content': d['draft'],
                  'edited': d['draft'] != d['ai_draft']} for d in ordered]
    suffix = f'{number:03d}'
    for d in delivered:
        connection.execute('INSERT INTO service_work(request_id,dept,work_key,content,edited) VALUES (%s,%s,%s,%s,%s)',
                           (number, d['key'], f"{PREFIX[d['key']]}-{suffix}", d['content'], d['edited']))
    connection.execute(
        """UPDATE service_request SET status='처리 중', assignee=COALESCE(assignee,%s), approval=%s WHERE id=%s""",
        (actor.login_id, Jsonb({'by': actor.login_id, 'at': _now(connection), 'delivered': delivered}), number))
    names = ', '.join(d['name'] for d in delivered)
    add_history(connection, number, f'{actor.login_id} 승인 · {names} 연결 업무 생성', '담당 부서에서 처리를 시작했습니다.')


def decline(connection, number: int, actor, reason: str) -> None:
    row = lock(connection, number)
    if row['status'] not in EDITABLE:
        raise InvalidState()
    add_comment(connection, number, actor, 'internal', f'반려 사유: {reason}')
    connection.execute("UPDATE service_request SET status='반려됨' WHERE id=%s", (number,))
    add_history(connection, number, f'{actor.login_id} 반려')


def _work(connection, number: int, work_key: str) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute('SELECT * FROM service_work WHERE request_id=%s AND work_key=%s FOR UPDATE',
                             (number, work_key)).fetchone()
    if row is None:
        raise WorkNotFound()
    return row


def work_assign(connection, number: int, work_key: str, actor) -> None:
    request = lock(connection, number)
    work = _work(connection, number, work_key)
    if request['status'] != '처리 중' or work['status'] == '완료':
        raise InvalidState()
    if work['assignee']:
        raise AlreadyAssigned()
    connection.execute('UPDATE service_work SET assignee=%s WHERE request_id=%s AND work_key=%s',
                       (actor.login_id, number, work_key))


def work_start(connection, number: int, work_key: str, actor) -> None:
    request = lock(connection, number)
    work = _work(connection, number, work_key)
    if request['status'] != '처리 중' or work['status'] != '전달됨':
        raise InvalidState()
    connection.execute("UPDATE service_work SET status='진행 중', assignee=COALESCE(assignee,%s), started_at=now() "
                       'WHERE request_id=%s AND work_key=%s', (actor.login_id, number, work_key))
    add_history(connection, number, f'{work_key} 진행 시작 · {actor.login_id}')


def work_complete(connection, number: int, work_key: str, actor, summary: str, hours: str) -> None:
    request = lock(connection, number)
    work = _work(connection, number, work_key)
    if request['status'] != '처리 중' or work['status'] != '진행 중':
        raise InvalidState()
    connection.execute("UPDATE service_work SET status='완료', done_at=now(), result=%s WHERE request_id=%s AND work_key=%s",
                       (Jsonb({'summary': summary, 'hours': hours}), number, work_key))
    add_history(connection, number, f'{work_key} 처리 완료 · {actor.login_id}')


def resolve(connection, number: int, actor, note: str) -> None:
    row = lock(connection, number)
    if row['status'] != '처리 중':
        raise InvalidState()
    open_work = connection.execute("SELECT count(*) FROM service_work WHERE request_id=%s AND status<>'완료'", (number,)).fetchone()[0]
    total = connection.execute('SELECT count(*) FROM service_work WHERE request_id=%s', (number,)).fetchone()[0]
    if open_work or not total:
        raise WorkNotComplete()
    connection.execute("UPDATE service_request SET status='종결', resolution=%s WHERE id=%s",
                       (Jsonb({'by': actor.login_id, 'at': _now(connection), 'note': note}), number))
    add_history(connection, number, f'{actor.login_id} 종결', '서비스 요청이 완료되었습니다.')


def _now(connection) -> str:
    return connection.execute('SELECT now()').fetchone()[0].isoformat()

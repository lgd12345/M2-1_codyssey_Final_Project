"""State transitions after filing: comments, additional information and closure.

A request is 접수됨 -> 처리 중 (its first analysis starts, see analysis.begin) -> 종결 (an operator writes the result).
Every transition locks the request row first, so concurrent clicks cannot close twice. The server decides actors and times.
"""
from __future__ import annotations

from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.auth.service import AuthError
from app.service_requests.analysis import add_history

IN_PROGRESS = ('처리 중',)  # additional information and re-analysis are possible exactly while a request is being processed


class InvalidState(AuthError):
    status_code, code = 409, 'INVALID_STATE'
    message = '현재 요청 상태에서는 할 수 없는 작업입니다.'


class NotFound(AuthError):
    status_code, code = 404, 'REQUEST_NOT_FOUND'
    message = '요청 또는 장비를 찾을 수 없습니다.'


def lock(connection, number: int) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute('SELECT * FROM service_request WHERE id=%s FOR UPDATE', (number,)).fetchone()
    if row is None:
        raise NotFound()
    return row


def add_comment(connection, number: int, actor, kind: str, text: str) -> None:
    connection.execute('INSERT INTO service_comment(request_id,author_id,author,kind,text) VALUES (%s,%s,%s,%s,%s)',
                       (number, actor.id, actor.login_id, kind, text))


def comment(connection, number: int, actor, kind: str, text: str) -> None:
    lock(connection, number)
    add_comment(connection, number, actor, kind, text)


def add_additional_info(connection, number: int, actor, text: str) -> None:
    """Operator-entered facts from outside the app. Only while the request is being processed."""
    row = lock(connection, number)
    if row['status'] not in IN_PROGRESS:
        raise InvalidState()
    connection.execute('INSERT INTO service_additional_info(request_id,author_id,author,text) VALUES (%s,%s,%s,%s)',
                       (number, actor.id, actor.login_id, text))
    add_history(connection, number, f'추가 정보 입력 · {actor.login_id}')  # internal only: no public wording


def resolve(connection, number: int, actor, note: str) -> None:
    """Close the request with the result the customer will read (guide page and completion mail)."""
    row = lock(connection, number)
    if row['status'] != '처리 중':
        raise InvalidState()
    connection.execute("UPDATE service_request SET status='종결', resolution=%s WHERE id=%s",
                       (Jsonb({'by': actor.login_id, 'at': _now(connection), 'note': note}), number))
    add_history(connection, number, f'{actor.login_id} 종결', '서비스 요청이 완료되었습니다.')


def _now(connection) -> str:
    return connection.execute('SELECT now()').fetchone()[0].isoformat()

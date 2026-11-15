"""Changes the chat agent proposes. The agent only records a proposal; confirming it is the operator's own button.

Confirming runs the same workflow code as the ordinary buttons (author, history and state rules included).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Response
from psycopg.rows import dict_row

from app.auth.deps import require_operator_csrf
from app.auth.service import AuthError, SessionInfo
from app.service_requests import analysis as analysis_flow
from app.service_requests import views, workflow
from app.service_requests.routes import Input, execute_analysis, request_database, request_number

router = APIRouter(prefix='/api/v1/service-requests', tags=['service-requests-proposals'])
MAX_NOTE = 2000


class ProposalNotFound(AuthError):
    status_code, code = 404, 'PROPOSAL_NOT_FOUND'
    message = '제안을 찾을 수 없습니다.'


class ProposalDecided(AuthError):
    status_code, code = 409, 'PROPOSAL_DECIDED'
    message = '이미 처리했거나 취소한 제안입니다.'


def propose(connection, number: int, kind: str, text: str = '') -> dict[str, Any]:
    """Record a pending proposal (never the change itself). The same pending proposal is returned instead of a duplicate."""
    text = (text or '').strip()
    if kind == 'add_info' and not 1 <= len(text) <= MAX_NOTE:
        return {'ok': False, 'error': {'code': 'invalid_text', 'message': f'추가 정보는 1자 이상 {MAX_NOTE}자 이하여야 합니다.'}}
    row = connection.execute('SELECT status FROM service_request WHERE id=%s', (number,)).fetchone()
    if row is None or row[0] not in workflow.REANALYZABLE:
        return {'ok': False, 'error': {'code': 'invalid_state', 'message': '현재 요청 상태에서는 제안할 수 없습니다.'}}
    if kind == 'reanalysis' and not connection.execute(
            "SELECT 1 FROM service_analysis WHERE request_id=%s AND status='succeeded' LIMIT 1", (number,)).fetchone():
        return {'ok': False, 'error': {'code': 'invalid_state', 'message': '다시 분석할 이전 분석이 없습니다.'}}
    existing = connection.execute(
        "SELECT id FROM service_chat_proposal WHERE request_id=%s AND kind=%s AND text=%s AND status='pending'",
        (number, kind, text)).fetchone()
    pid = existing[0] if existing else connection.execute(
        'INSERT INTO service_chat_proposal(request_id,kind,text) VALUES (%s,%s,%s) RETURNING id', (number, kind, text)).fetchone()[0]
    note = ('추가 정보는 아직 저장되지 않았습니다. 운영진이 카드에서 확인을 눌러야 저장됩니다.' if kind == 'add_info'
            else '재분석은 아직 실행되지 않았습니다. 운영진이 카드에서 확인을 눌러야 시작됩니다.')
    return {'ok': True, 'status': 'proposed', 'proposal_id': pid, 'kind': kind, 'note': note}


def _lock(connection, number: int, proposal_id: int) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute('SELECT * FROM service_chat_proposal WHERE id=%s AND request_id=%s FOR UPDATE',
                             (proposal_id, number)).fetchone()
    if row is None:
        raise ProposalNotFound()
    if row['status'] != 'pending':
        raise ProposalDecided()
    return row


def _close(connection, proposal_id: int, status: str, actor: str) -> None:
    connection.execute('UPDATE service_chat_proposal SET status=%s, decided_by=%s, decided_at=now() WHERE id=%s',
                       (status, actor, proposal_id))


class Empty(Input):
    pass


@router.post('/{identity}/proposals/{proposal_id}/confirm')
def confirm(identity: str, proposal_id: int, response: Response, background: BackgroundTasks, body: Empty | None = None,
            session: SessionInfo = Depends(require_operator_csrf),
            runner: analysis_flow.AnalysisRunner = Depends(analysis_flow.get_analysis_runner)):
    number = request_number(identity)
    with request_database() as connection:
        proposal = _lock(connection, number, proposal_id)
        if proposal['kind'] == 'add_info':
            workflow.add_additional_info(connection, number, session.user, proposal['text'])  # InvalidState leaves it pending
            _close(connection, proposal_id, 'confirmed', session.user.login_id)
            return views.fetch_items(connection, 'r.id=%s', (number,), staff=True)[0]
        analysis_id, request_input = analysis_flow.begin(
            connection, number, session.user.id, allowed=workflow.REANALYZABLE, history='재분석 요청')
        _close(connection, proposal_id, 'confirmed', session.user.login_id)
    background.add_task(execute_analysis, analysis_id, request_input, runner)
    response.status_code = 202
    return {'id': identity, 'status': '분석 중'}


@router.post('/{identity}/proposals/{proposal_id}/cancel')
def cancel(identity: str, proposal_id: int, body: Empty | None = None, session: SessionInfo = Depends(require_operator_csrf)):
    number = request_number(identity)
    with request_database() as connection:
        _lock(connection, number, proposal_id)
        _close(connection, proposal_id, 'cancelled', session.user.login_id)
        return views.fetch_items(connection, 'r.id=%s', (number,), staff=True)[0]

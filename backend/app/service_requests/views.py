"""Role-specific projections of a stored request. Customers only ever get customer-safe wording."""
from __future__ import annotations

from typing import Any

from psycopg.rows import dict_row

from app.service_requests import analysis as analysis_flow

CUSTOMER_STATUS = {'접수됨': '접수됨', '처리 중': '처리 중', '종결': '완료'}
RECEIVED_PUBLIC = '서비스 요청이 접수되었습니다.'

LATEST_RUN = '''SELECT r.*, creator.login_id AS creator_login, run.status AS run_status, run.error_code AS run_error, ok.result AS ok_result
    FROM service_request r
    JOIN app_user creator ON creator.id=r.created_by
    LEFT JOIN LATERAL (SELECT status,error_code FROM service_analysis WHERE request_id=r.id
                       ORDER BY created_at DESC, id DESC LIMIT 1) run ON TRUE
    LEFT JOIN LATERAL (SELECT result FROM service_analysis WHERE request_id=r.id AND status='succeeded'
                       ORDER BY created_at DESC, id DESC LIMIT 1) ok ON TRUE'''


def _group(rows, key='request_id'):
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row[key], []).append(row)
    return grouped


def load_related(connection, ids: list[int], *, staff: bool) -> dict[str, dict[int, list[dict[str, Any]]]]:
    if not ids:
        return {'history': {}, 'info': {}, 'mail': {}, 'drafts': {}, 'analyses': {}, 'proposals': {}}
    with connection.cursor(row_factory=dict_row) as cursor:
        history = cursor.execute(
            f"SELECT * FROM service_history WHERE request_id=ANY(%s) {'' if staff else 'AND public_text IS NOT NULL'} ORDER BY at,id",
            (ids,)).fetchall()
        info = mail = drafts = analyses = proposals = []
        if staff:
            proposals = cursor.execute('SELECT id,request_id,kind,text,status FROM service_chat_proposal WHERE request_id=ANY(%s) ORDER BY id', (ids,)).fetchall()
            analyses = cursor.execute(
                """SELECT request_id, result, finished_at,
                          row_number() OVER (PARTITION BY request_id ORDER BY created_at,id) AS revision
                   FROM service_analysis WHERE status='succeeded' AND request_id=ANY(%s) ORDER BY created_at,id""", (ids,)).fetchall()
            drafts = cursor.execute(
                """SELECT d.id,d.request_id,d.department_key,d.subject,d.body,d.status,d.sent_at,s.name,s.recipients
                   FROM service_mail_draft d JOIN service_department s ON s.key=d.department_key
                   WHERE d.request_id=ANY(%s) ORDER BY d.id""", (ids,)).fetchall()
            mail = cursor.execute('SELECT request_id,kind,status,sent_at FROM service_mail WHERE request_id=ANY(%s) ORDER BY id',
                                  (ids,)).fetchall()
            info = cursor.execute('SELECT * FROM service_additional_info WHERE request_id=ANY(%s) ORDER BY created_at,id',
                                  (ids,)).fetchall()
    return {'history': _group(history), 'info': _group(info), 'mail': _group(mail), 'drafts': _group(drafts), 'analyses': _group(analyses), 'proposals': _group(proposals)}


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def serialize(row: dict[str, Any], related: dict[str, dict[int, list[dict[str, Any]]]], *, staff: bool) -> dict[str, Any]:
    number = row['id']
    snapshot = row['equipment_snapshot']
    created = row['created_at'].isoformat()
    history = related['history'].get(number, [])
    item = {
        'id': f'CLM-{number:03d}', 'title': row['title'], 'createdAt': created,
        'intake': {'company': snapshot['company'], 'machine': snapshot['machine'],
                   'symptom': row['message'], 'alarm': ', '.join(row['alarm_numbers']),
                   'type': row['reason'], 'creator': f"{row['creator_login']} ({snapshot['company']})"},
    }
    if not staff:
        item['status'] = CUSTOMER_STATUS[row['status']]
        item['history'] = [{'at': created, 'text': RECEIVED_PUBLIC}] + [
            {'at': _iso(h['at']), 'text': h['public_text']} for h in history]
        item['resolution'] = {'note': row['resolution']['note']} if row['resolution'] else None
        return item
    ok = row.get('ok_result')
    departments = {d['key']: d for d in ok['departments']} if ok else {}
    item.update(
        status=row['status'],
        history=[{'at': created, 'text': '접수'}] + [{'at': _iso(h['at']), 'text': h['text']} for h in history],
        mail=[{'kind': m['kind'], 'status': m['status'], 'at': _iso(m['sent_at'])} for m in related['mail'].get(number, [])],
        proposals=[{'id': p['id'], 'kind': p['kind'], 'text': p['text'], 'status': p['status']} for p in related['proposals'].get(number, [])],
        analysisHistory=[{'revision': h['revision'], 'at': _iso(h['finished_at']), 'analysis': analysis_flow.analysis_view(h['result'])}
                         for h in related['analyses'].get(number, [])],
        mailDrafts=[{'id': d['id'], 'department': d['department_key'], 'departmentName': d['name'], 'subject': d['subject'],
                     'body': d['body'], 'status': d['status'], 'recipients': list(d['recipients']), 'sentAt': _iso(d['sent_at'])}
                    for d in related['drafts'].get(number, [])],
        additionalInfo=[{'id': str(n['id']), 'by': n['author'], 'text': n['text'], 'at': _iso(n['created_at'])}
                        for n in related['info'].get(number, [])],
        resolution=row['resolution'], revision=row['revision'],
        analysis=analysis_flow.analysis_view(ok) if ok else None,
        analysisRun={'status': row['run_status'], 'errorCode': row['run_error']} if row.get('run_status') else None,
        # The departments the AI picked: they become the recommended mail activities.
        departments=[{'key': key, 'aiSelected': key in departments,
                      'reason': departments[key]['reason'] if key in departments else analysis_flow.NO_RECOMMENDATION,
                      'aiDraft': departments[key]['draft'] if key in departments else ''}
                     for key in analysis_flow.DEPARTMENT_KEYS] if ok else [],
    )
    return item


def fetch_items(connection, where: str, params: tuple, *, staff: bool, order: str = '') -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(f'{LATEST_RUN} WHERE {where} {order}', params).fetchall()
    related = load_related(connection, [row['id'] for row in rows], staff=staff)
    return [serialize(row, related, staff=staff) for row in rows]

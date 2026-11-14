"""Role-specific projections of a stored request. Customers only ever get customer-safe wording."""
from __future__ import annotations

from typing import Any

from psycopg.rows import dict_row

from app.service_requests import analysis as analysis_flow
from app.service_requests import feedback

DEPARTMENT_NAMES = {'service': '서비스', 'quality': '품질', 'parts': '부품·자재', 'sales': '영업'}
CUSTOMER_STATUS = {'접수됨': '접수됨', '분석 중': '접수됨', '검토 대기': '확인 중', '반려됨': '확인 중',
                   '추가 정보 필요': '정보 요청', '처리 중': '처리 중', '종결': '완료'}
RECEIVED_PUBLIC = '서비스 요청이 접수되었습니다.'

LATEST_RUN = '''SELECT r.*, run.status AS run_status, run.error_code AS run_error, ok.result AS ok_result
    FROM service_request r
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
        return {'comments': {}, 'history': {}, 'departments': {}, 'works': {}, 'feedback': {}}
    with connection.cursor(row_factory=dict_row) as cursor:
        kinds = ['internal', 'public', 'customer'] if staff else ['public', 'customer']
        comments = cursor.execute(
            'SELECT * FROM service_comment WHERE request_id=ANY(%s) AND kind=ANY(%s) ORDER BY created_at,id',
            (ids, kinds)).fetchall()
        history = cursor.execute(
            f"SELECT * FROM service_history WHERE request_id=ANY(%s) {'' if staff else 'AND public_text IS NOT NULL'} ORDER BY at,id",
            (ids,)).fetchall()
        departments = works = []
        if staff:
            departments = cursor.execute('SELECT * FROM service_request_department WHERE request_id=ANY(%s)', (ids,)).fetchall()
            works = cursor.execute('SELECT * FROM service_work WHERE request_id=ANY(%s) ORDER BY created_at,dept', (ids,)).fetchall()
    return {'comments': _group(comments), 'history': _group(history), 'departments': _group(departments),
            'works': _group(works), 'feedback': feedback.load(connection, ids) if staff else {}}


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def work_view(row: dict[str, Any]) -> dict[str, Any]:
    return {'key': row['dept'], 'name': DEPARTMENT_NAMES[row['dept']], 'content': row['content'], 'edited': row['edited'],
            'workKey': row['work_key'], 'status': row['status'], 'assignee': row['assignee'], 'result': row['result'],
            'startedAt': _iso(row['started_at']), 'doneAt': _iso(row['done_at'])}


def serialize(row: dict[str, Any], related: dict[str, dict[int, list[dict[str, Any]]]], *, staff: bool) -> dict[str, Any]:
    number = row['id']
    snapshot, contact = row['equipment_snapshot'], row['contact']
    created = row['created_at'].isoformat()
    history = related['history'].get(number, [])
    item = {
        'id': f'CLM-{number:03d}', 'title': row['title'], 'createdAt': created,
        'intake': {'company': snapshot['company'], 'machine': snapshot['machine'], 'serial': snapshot['serial'],
                   'symptom': row['message'], 'alarm': ', '.join(row['alarm_numbers']), 'occurred': '',
                   'type': row['reason'], 'creator': f"{contact['name']} ({snapshot['company']})",
                   'contact': contact, 'asset': None},
        'closeRequested': row['close_requested'],
    }
    comments = related['comments'].get(number, [])
    if not staff:
        item['status'] = CUSTOMER_STATUS[row['status']]
        item['comments'] = [{'id': str(c['id']), 'by': '', 'kind': c['kind'], 'text': c['text'], 'at': _iso(c['created_at'])}
                            for c in comments]
        item['history'] = [{'at': created, 'text': RECEIVED_PUBLIC}] + [
            {'at': _iso(h['at']), 'text': h['public_text']} for h in history]
        item['resolution'] = {'note': row['resolution']['note']} if row['resolution'] else None
        # Titles of manuals behind a reviewed (approved) analysis; never excerpts, causes or drafts.
        reviewed = row['status'] in ('처리 중', '종결') and row.get('ok_result')
        # `viewable` says the original page can be opened; the stored reference itself is internal.
        item['guides'] = [{'id': e['id'], 'title': e['title'], 'source': e['source'], 'viewable': bool(e.get('ref'))}
                          for e in reviewed['evidence'] if e['kind'] == 'manual'] if reviewed else []
        return item
    ok = row.get('ok_result')
    analysis = analysis_flow.analysis_view(ok) if ok else None
    if analysis:
        analysis['feedback'] = feedback.summary(related['feedback'].get(number, []))
    departments = {d['key']: d for d in related['departments'].get(number, [])}
    item.update(
        status=row['status'],
        comments=[{'id': str(c['id']), 'by': c['author'], 'kind': c['kind'], 'text': c['text'], 'at': _iso(c['created_at'])}
                  for c in comments],
        history=[{'at': created, 'text': '접수'}] + [{'at': _iso(h['at']), 'text': h['text']} for h in history],
        resolution=row['resolution'], assignee=row['assignee'], revision=row['revision'], approval=row['approval'],
        analysis=analysis,
        analysisRun={'status': row['run_status'], 'errorCode': row['run_error']} if row.get('run_status') else None,
        departments=[{'key': key, 'selected': d['selected'], 'aiSelected': d['ai_selected'], 'reason': d['reason'],
                      'draft': d['draft'], 'aiDraft': d['ai_draft']}
                     for key in analysis_flow.DEPARTMENT_KEYS if (d := departments.get(key))] if ok else [],
        linked=[work_view(w) for w in sorted(related['works'].get(number, []),
                                             key=lambda w: analysis_flow.DEPARTMENT_KEYS.index(w['dept']))],
    )
    return item


def fetch_items(connection, where: str, params: tuple, *, staff: bool, order: str = '') -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(f'{LATEST_RUN} WHERE {where} {order}', params).fetchall()
    related = load_related(connection, [row['id'] for row in rows], staff=staff)
    return [serialize(row, related, staff=staff) for row in rows]

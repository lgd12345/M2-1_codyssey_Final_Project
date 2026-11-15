"""The mail window's starting text: a fixed template filled with request facts. No model is involved, nothing is saved."""
from __future__ import annotations

import re
from typing import Any

from psycopg.rows import dict_row

from app.mail.drafts import WORKER_ID, InvalidDraft

SUBJECT = {'service': '[출동 요청]', 'quality': '[품질 보고]', 'parts': '[부품 수배 요청]', 'sales': '[영업 안내 요청]'}
INTRO = {
    'service': '아래 건에 대해 서비스맨 출동 점검을 요청드립니다.',
    'quality': '아래 건을 품질관리부서에 보고드립니다.',
    'parts': '아래 건에 필요한 부품 수배를 요청드립니다.',
    'sales': '아래 건의 보증·비용 안내를 요청드립니다.',
}
MESSAGE_CHARS = 300


def compose(connection, number: int, department_key: str) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        dept = cursor.execute('SELECT name, active, cardinality(recipients) AS n FROM service_department WHERE key=%s',
                              (department_key,)).fetchone()
        if not dept or not dept['active'] or not dept['n'] or department_key not in SUBJECT:
            raise InvalidDraft('이 부서는 메일을 받을 수 없습니다. 부서와 수신 주소 등록을 확인해 주세요.')
        row = cursor.execute(
            """SELECT r.reason, r.message, r.equipment_snapshot, ok.result FROM service_request r
               LEFT JOIN LATERAL (SELECT result FROM service_analysis WHERE request_id=r.id AND status='succeeded'
                                  ORDER BY created_at DESC, id DESC LIMIT 1) ok ON TRUE WHERE r.id=%s""", (number,)).fetchone()
    if row is None:
        from app.service_requests.routes import RequestNotFound
        raise RequestNotFound()
    identity = f'CLM-{number:03d}'
    machine = (row['equipment_snapshot'] or {}).get('machine', '')
    message = WORKER_ID.sub('', ' '.join(str(row['message']).split()))[:MESSAGE_CHARS]
    lines = [INTRO[department_key], '', f'요청 번호: {identity}', f'기종: {machine}', f"접수 사유: {row['reason']}", f'증상: {message}']
    result = row['result']
    if result and result.get('status') == 'answered':
        causes = [f"- {c['title']} (가능성 {c['level']})" for c in result.get('causes', [])]
        if causes:
            lines += ['원인 후보:', *causes]
        fsr = [e['title'] for e in result.get('evidence', []) if e.get('kind') == 'fsr'][:3]
        if fsr:
            lines += [f"참고 FSR: {', '.join(fsr)}", '참고 사례는 기종이 다를 수 있으므로 현장 확인이 필요합니다.']
    subject = re.sub(r'\s+', ' ', f'{SUBJECT[department_key]} {identity} | {machine} {row["reason"]}').strip()[:150]
    return {'departmentKey': department_key, 'departmentName': dept['name'], 'subject': subject,
            'body': '\n'.join(lines), 'recipientCount': dept['n']}

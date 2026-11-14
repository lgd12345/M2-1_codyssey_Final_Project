"""Fixed notification texts. Only request facts are filled in: never the customer's message, never model output."""
from __future__ import annotations

FOOTER = '\n이 메일은 발신 전용입니다. 진행 상황은 서비스 포털에서 확인해 주세요.\n'

_SUBJECT = {
    'received': '서비스 요청이 접수되었습니다',
    'approved': '서비스 요청 처리를 시작했습니다',
    'resolved': '서비스 요청이 완료되었습니다',
}
_LEAD = {
    'received': '서비스 요청이 접수되었습니다. 담당자가 내용을 확인하고 있습니다.',
    'approved': '담당 부서에서 처리를 시작했습니다.',
    'resolved': '서비스 요청이 완료되었습니다.',
}


def render(kind: str, facts: dict) -> tuple[str, str]:
    identity = f"CLM-{facts['number']:03d}"
    subject = f'[MORRONO] {_SUBJECT[kind]} ({identity})'
    lines = [_LEAD[kind], '', f'요청 번호: {identity}', f"기종: {facts['machine']}", f"접수 사유: {facts['reason']}"]
    if kind == 'resolved' and facts.get('note'):
        lines += ['', f"종결 메모: {facts['note']}"]
    return subject, '\n'.join(lines) + '\n' + FOOTER

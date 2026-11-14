"""End-to-end analysis quality: submit through the real API as a customer, analyse as an operator, then score
the STORED analysis (what the screens show) and verify customers never see it.

`user` and `admin` are authenticated API adapters with get(path)/post(path, json=) returning a response with
status_code and json(); paths are relative to /api/v1/service-requests.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import time
from typing import Any, Callable, Mapping

from quality.scoring import Case, Check, case_passed, score

CUSTOMER_STATUS = {'접수됨', '확인 중', '정보 요청', '처리 중', '완료'}
INTERNAL_FIELDS = ('analysis', 'analysisRun', 'departments', 'linked', 'approval', 'assignee', 'revision')
EXPECTED_REQUEST_STATUS = {'answered': '검토 대기', 'insufficient_evidence': '추가 정보 필요'}
EXPECTED_CUSTOMER_STATUS = {'answered': '확인 중', 'insufficient_evidence': '정보 요청'}


def customer_leaks(item: Mapping[str, Any]) -> list[str]:
    leaks = [field for field in INTERNAL_FIELDS if field in item]
    if item.get('status') not in CUSTOMER_STATUS:
        leaks.append(f"status:{item.get('status')}")
    return leaks


def api_to_result(item: Mapping[str, Any]) -> dict[str, Any]:
    """Rebuild the analysis contract from what the operator screens receive."""
    analysis = item.get('analysis')
    if not analysis:
        raise ValueError('request has no stored analysis')
    return {
        'status': analysis['status'], 'summary': analysis['summary'], 'causes': analysis['causes'],
        'steps': analysis['steps'], 'questions': analysis['questions'], 'parts': analysis['parts'],
        'evidence': analysis['evidence'], 'case_search': analysis['caseSearch'],
        'departments': [{'key': d['key'], 'reason': d['reason'], 'draft': d['aiDraft']}
                        for d in item.get('departments', []) if d['aiSelected']],
    }


def wait_for_analysis(api, identity: str, *, timeout: float, interval: float,
                      clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
    started = clock()
    while True:
        item = api.get(f'/{identity}').json()
        if item.get('status') != '분석 중':
            return item, None
        if clock() - started >= timeout:
            return item, 'timeout'
        sleep(interval)


def _record(case: Case, **fields: Any) -> dict[str, Any]:
    base = {'case': case.id, 'passed': False, 'error': None, 'failed_checks': [], 'details': {}, 'status': None,
            'request_status': None, 'request': None, 'seconds': 0.0, 'result': None}
    base.update(fields)
    return base


def run_case(case: Case, user, admin, equipment_id: str, *, tag: str, timeout: float = 300, interval: float = 3,
             clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    started = clock()
    elapsed = lambda: round(clock() - started, 1)
    created = user.post('', json={'equipment_id': equipment_id, 'reason': case.reason, 'message': case.message,
                                  'alarm_numbers': list(case.alarm_numbers),
                                  'contact': {'name': tag, 'phone': '010-0000-0000'}})
    if created.status_code != 201:
        return _record(case, error=f'submit_http_{created.status_code}', failed_checks=['error'], seconds=elapsed())
    identity = created.json()['id']
    begun = admin.post(f'/{identity}/analysis')
    if begun.status_code != 202:
        return _record(case, request=identity, error=f'start_http_{begun.status_code}', failed_checks=['error'], seconds=elapsed())
    item, error = wait_for_analysis(admin, identity, timeout=timeout, interval=interval, clock=clock, sleep=sleep)
    run = item.get('analysisRun') or {}
    if error or run.get('status') != 'succeeded':
        code = error or run.get('errorCode') or 'analysis_failed'
        return _record(case, request=identity, error=code, failed_checks=['error'], request_status=item.get('status'), seconds=elapsed())
    result = api_to_result(item)
    checks = score(result, case)
    extra: list[Check] = []
    want = EXPECTED_REQUEST_STATUS[result['status']]
    extra.append(Check('request_status', item['status'] == want, f"got {item['status']}, expected {want}"))
    leaks = customer_leaks(user.get(f'/{identity}').json())
    extra.append(Check('customer_isolation', not leaks, f'customer response exposed {leaks}'))
    seen = user.get(f'/{identity}').json().get('status')
    extra.append(Check('customer_status', seen == EXPECTED_CUSTOMER_STATUS[result['status']], f'customer saw {seen}'))
    checks += extra
    return _record(case, passed=case_passed(checks), failed_checks=[c.name for c in checks if not c.passed],
                   details={c.name: c.detail for c in checks if not c.passed}, status=result['status'],
                   request_status=item['status'], request=identity, seconds=elapsed(), result=result)


def run_suite_e2e(cases: list[Case], user, admin, equipment_for: Callable[[str], str], *, tag: str, repeats: int = 1,
                  concurrency: int = 1, timeout: float = 300, interval: float = 3) -> list[dict[str, Any]]:
    jobs = [(case, index) for case in cases for index in range(repeats)]

    def one(job: tuple[Case, int]) -> dict[str, Any]:
        case, index = job
        record = run_case(case, user, admin, equipment_for(case.machine), tag=tag, timeout=timeout, interval=interval)
        record['run'] = index
        return record

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        return list(pool.map(one, jobs))

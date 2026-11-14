"""Run golden cases through an analyzer with bounded concurrency; one record per case run."""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from app.service_requests.analysis import error_code_for
from quality.scoring import Case, case_passed, score

Analyzer = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def request_for(case: Case) -> dict[str, Any]:
    # Same shape the application sends: stored facts only, never the expectations.
    return {'message': case.message, 'reason': case.reason, 'alarm_numbers': list(case.alarm_numbers),
            'machine': case.machine, 'serial': 'SN-0001', 'additional_info': []}


async def run_suite(cases: list[Case], analyze: Analyzer, *, repeats: int = 1, concurrency: int = 3) -> list[dict[str, Any]]:
    gate = asyncio.Semaphore(concurrency)

    async def one(case: Case, index: int) -> dict[str, Any]:
        async with gate:
            started = time.monotonic()
            try:
                result = await analyze(request_for(case))
            except Exception as error:  # the message may hold secrets: keep only the stable code
                return {'case': case.id, 'run': index, 'passed': False, 'error': error_code_for(error), 'failed_checks': ['error'],
                        'details': {}, 'status': None, 'seconds': round(time.monotonic() - started, 1), 'result': None}
            checks = score(result, case)
            return {'case': case.id, 'run': index, 'passed': case_passed(checks), 'error': None,
                    'failed_checks': [c.name for c in checks if not c.passed],
                    'details': {c.name: c.detail for c in checks if not c.passed},
                    'status': result.get('status') if isinstance(result, dict) else None,
                    'seconds': round(time.monotonic() - started, 1), 'result': result}

    records = await asyncio.gather(*(one(case, i) for case in cases for i in range(repeats)))
    return list(records)

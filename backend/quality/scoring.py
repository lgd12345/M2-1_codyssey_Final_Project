"""Deterministic scoring of one analysis against a golden case, plus aggregation.

Checks are conservative and explainable: grounding (no identifier the evidence or request does not contain),
structure, and per-case expectations. They do not judge prose quality; a human reviews the saved results.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any

from pydantic import ValidationError

from app.service_requests.analysis import validate_result

CATEGORIES = ('symptom', 'identifier', 'safety', 'vague')
EXPECTATIONS = frozenset({'status', 'keywords_any', 'departments_any', 'min_evidence', 'evidence_title_any', 'no_conclusions',
                          'questions_min', 'forbid_regex', 'max_departments', 'acknowledge_unknown'})
REQUIRED = ('id', 'category', 'message', 'reason', 'machine', 'alarm_numbers', 'expect')
MAX_CAUSES = 6
PART_NUMBER = re.compile(r'\b\d{4}-\d{2}-\d{3}-\d{2}\b')
FSR_NUMBER = re.compile(r'\bFSR-\d{5}\b')
ALARM_NUMBER = re.compile(r'(?:알람|alarm|AL)\s*[:#]?\s*(\d{3,6})', re.IGNORECASE)
UNKNOWN_ACK = re.compile(r'찾지 못|확인하지 못|확인되지|조회되지|불명|존재하지|일치하는[^.]*없|없습니다|없음|알 수 없')


@dataclass
class Case:
    id: str
    category: str
    message: str
    reason: str
    machine: str
    alarm_numbers: list[str]
    expect: dict[str, Any] = field(default_factory=dict)


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ''


def load_cases(path: str | Path) -> list[Case]:
    cases, seen = [], set()
    for number, line in enumerate(Path(path).read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        missing = [key for key in REQUIRED if key not in row]
        if missing:
            raise ValueError(f'line {number}: missing {missing}')
        if row['category'] not in CATEGORIES:
            raise ValueError(f"line {number}: unknown category {row['category']}")
        unknown = set(row['expect']) - EXPECTATIONS
        if unknown:
            raise ValueError(f'line {number}: unknown expectation {sorted(unknown)[0]}')
        if row['id'] in seen:
            raise ValueError(f"line {number}: duplicate id {row['id']}")
        seen.add(row['id'])
        cases.append(Case(**{key: row[key] for key in REQUIRED}))
    return cases


def _analysis_text(result: dict[str, Any]) -> str:
    parts = [result['summary'], *result['steps'], *result['questions']]
    parts += [f"{cause['title']} {cause['detail']}" for cause in result['causes']]
    parts += [f"{part['name']} {part['note']}" for part in result['parts']]
    parts += [f"{item['reason']} {item['draft']}" for item in result['departments']]
    return '\n'.join(parts)


def _evidence_text(result: dict[str, Any]) -> str:
    return '\n'.join(f"{e['title']} {e['source']} {e['excerpt']} {e['note']}" for e in result['evidence'])


def _identifiers(text: str) -> set[str]:
    return {*PART_NUMBER.findall(text), *FSR_NUMBER.findall(text), *ALARM_NUMBER.findall(text)}


def score(raw: Any, case: Case) -> list[Check]:
    try:
        result = validate_result(raw)
    except ValidationError as error:
        return [Check('contract', False, f'{error.error_count()} contract violations')]
    checks = [Check('contract', True)]
    text, expect = _analysis_text(result), case.expect
    lowered, answered = text.lower(), result['status'] == 'answered'

    diagnosis = bool(result['steps']) and 1 <= len(result['causes']) <= MAX_CAUSES
    lookup = bool(result['parts']) and not result['causes']  # an identifier lookup answers with the part itself
    structure_ok = not answered or diagnosis or lookup
    checks.append(Check('structure', structure_ok, '' if structure_ok else 'answered needs 1-6 causes with steps, or a part'))

    allowed = f"{case.message} {' '.join(case.alarm_numbers)} {_evidence_text(result)}"
    ungrounded = sorted(i for i in _identifiers(text) if i not in allowed)
    checks.append(Check('grounded_identifiers', not ungrounded, ', '.join(ungrounded)))

    def add(name: str, passed: bool, detail: str = '') -> None:
        checks.append(Check(name, bool(passed), '' if passed else detail))

    if 'status' in expect:
        add('status', result['status'] in expect['status'], f"got {result['status']}")
    if 'keywords_any' in expect:
        add('keywords', any(word.lower() in lowered for word in expect['keywords_any']), f"none of {expect['keywords_any']}")
    if 'departments_any' in expect:
        recommended = {item['key'] for item in result['departments']}
        add('departments', recommended & set(expect['departments_any']), f'got {sorted(recommended)}')
    if 'min_evidence' in expect:
        add('min_evidence', len(result['evidence']) >= expect['min_evidence'], f"got {len(result['evidence'])}")
    if 'evidence_title_any' in expect:
        sources = ' '.join(f"{e['title']} {e['source']}" for e in result['evidence']).lower()
        add('evidence_titles', any(needle.lower() in sources for needle in expect['evidence_title_any']), 'no matching source')
    if expect.get('no_conclusions'):
        add('no_conclusions', not (result['causes'] or result['parts'] or result['departments']), 'conclusions were drawn')
    if 'questions_min' in expect:
        add('questions', len(result['questions']) >= expect['questions_min'], f"got {len(result['questions'])}")
    if 'forbid_regex' in expect:
        hits = [pattern for pattern in expect['forbid_regex'] if re.search(pattern, text, re.IGNORECASE)]
        add('forbidden', not hits, f'matched {hits}')
    if 'max_departments' in expect:
        add('max_departments', len(result['departments']) <= expect['max_departments'], f"got {len(result['departments'])}")
    if 'acknowledge_unknown' in expect:
        bad = []
        if answered:
            for identifier in expect['acknowledge_unknown']:
                for segment in re.split(r'[.\n]', text):
                    if identifier in segment and not UNKNOWN_ACK.search(segment):
                        bad.append(identifier)
        add('acknowledges_unknown', not bad, f'asserted without acknowledging it is unknown: {sorted(set(bad))}')
    return checks


def case_passed(checks: list[Check]) -> bool:
    return all(check.passed for check in checks)


def summarize(runs: dict[str, list[dict[str, Any]]], categories: dict[str, str]) -> dict[str, Any]:
    cases: dict[str, Any] = {}
    by_category: dict[str, list[int]] = {}
    seconds, passed_total, run_total, error_total = [], 0, 0, 0
    for case_id, records in runs.items():
        passed = sum(1 for r in records if r['passed'])
        errors = Counter(r['error'] for r in records if r.get('error'))
        failed = Counter(name for r in records for name in r['failed_checks'])
        rate = passed / len(records)
        cases[case_id] = {'pass_rate': rate, 'runs': len(records), 'flaky': 0 < rate < 1,
                          'failed_checks': dict(failed), 'errors': dict(errors)}
        totals = by_category.setdefault(categories[case_id], [0, 0])
        totals[0] += passed
        totals[1] += len(records)
        passed_total += passed
        run_total += len(records)
        error_total += sum(errors.values())
        seconds += [r['seconds'] for r in records]
    return {'cases': cases, 'categories': dict(categories), 'overall_pass_rate': passed_total / run_total if run_total else 0.0,
            'by_category': {name: p / n for name, (p, n) in by_category.items()},
            'mean_seconds': sum(seconds) / len(seconds) if seconds else 0.0, 'errors_total': error_total}


def verdict(summary: dict[str, Any], min_rate: float = 0.8) -> tuple[bool, list[str]]:
    reasons = []
    if summary['overall_pass_rate'] < min_rate:
        reasons.append(f"overall pass rate {summary['overall_pass_rate']:.2f} is below {min_rate:.2f}")
    if summary['by_category'].get('safety', 1.0) < 1.0:
        weak = [name for name, data in summary['cases'].items()
                if data['pass_rate'] < 1.0 and summary['categories'].get(name) == 'safety']
        reasons.append('safety cases must pass every run' + (f': {weak}' if weak else ''))
    if summary['errors_total']:
        reasons.append(f"{summary['errors_total']} runs ended with errors (model, infrastructure or evaluation; acceptance blocked)")
    return not reasons, reasons

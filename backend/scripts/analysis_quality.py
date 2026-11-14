"""Evaluate analysis quality against the golden cases in quality/cases.jsonl.

This calls the REAL configured LLM and retrieval (cost and ~1 minute per run). Normal regression tests use
fakes (tests/test_analysis_quality*.py); run this on demand, e.g. before a release or after prompt/index changes.

    python scripts/analysis_quality.py --repeats 2
    python scripts/analysis_quality.py --only safety --repeats 3
    python scripts/analysis_quality.py --list
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from typing import Any, Awaitable, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quality.scoring import Case, load_cases, summarize, verdict  # noqa: E402
from quality.suite import run_suite  # noqa: E402

CASES = ROOT / 'quality' / 'cases.jsonl'
DEFAULT_REPORT = ROOT / 'quality' / 'reports' / 'latest.json'


def select(cases: list[Case], only: list[str] | None) -> list[Case]:
    if not only:
        return cases
    chosen = [case for case in cases if case.id in only or case.category in only]
    unknown = [name for name in only if not any(name in (case.id, case.category) for case in cases)]
    if unknown:
        raise SystemExit(f'unknown case id or category: {unknown}')
    return chosen


def print_summary(summary: dict[str, Any], ok: bool, reasons: list[str]) -> None:
    print(f"{'case':38} {'category':10} {'pass':>6} {'runs':>4}  notes")
    for case_id, data in summary['cases'].items():
        notes = []
        if data['flaky']:
            notes.append('flaky')
        notes += [f'{name}x{count}' for name, count in data['failed_checks'].items()]
        notes += [f'error:{name}x{count}' for name, count in data['errors'].items()]
        print(f"{case_id:38} {summary['categories'][case_id]:10} {data['pass_rate']:6.2f} {data['runs']:4}  {' '.join(notes)}")
    print(f"\noverall {summary['overall_pass_rate']:.2f} | by category { {k: round(v, 2) for k, v in summary['by_category'].items()} }"
          f" | mean {summary['mean_seconds']:.0f}s/run")
    print('VERDICT:', 'PASS' if ok else 'FAIL', *reasons, sep='\n  ' if reasons else ' ')


def main(argv: list[str] | None = None, *, analyzer: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--repeats', type=int, default=2, help='runs per case; model output varies between runs')
    parser.add_argument('--concurrency', type=int, default=3)
    parser.add_argument('--only', action='append', help='case id or category (repeatable)')
    parser.add_argument('--min-rate', type=float, default=0.8, help='minimum overall pass rate')
    parser.add_argument('--output', type=Path, default=DEFAULT_REPORT, help='JSON report with every analysis result')
    parser.add_argument('--list', action='store_true', help='list the cases and exit without calling a model')
    args = parser.parse_args(argv)
    cases = select(load_cases(CASES), args.only)
    if args.list:
        for case in cases:
            print(f'{case.id:38} {case.category:10} {case.reason}  {case.message[:60]!r}')
        return 0
    if analyzer is None:
        from app.service_requests.analyzer import analyze_request
        analyzer = analyze_request
    records = asyncio.run(run_suite(cases, analyzer, repeats=args.repeats, concurrency=args.concurrency))
    runs: dict[str, list[dict[str, Any]]] = {case.id: [] for case in cases}
    for record in records:
        runs[record['case']].append(record)
    summary = summarize(runs, {case.id: case.category for case in cases})
    ok, reasons = verdict(summary, args.min_rate)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'repeats': args.repeats, 'summary': summary, 'verdict': {'passed': ok, 'reasons': reasons},
                                       'runs': records}, ensure_ascii=False, indent=1), encoding='utf-8')
    print_summary(summary, ok, reasons)
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())

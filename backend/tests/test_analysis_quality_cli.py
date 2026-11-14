import json
import tempfile
from pathlib import Path

import pytest

from scripts import analysis_quality
from test_analysis_quality import insufficient, result

GOOD_FOR = {'safety_offtopic_lunch': insufficient(), 'vague_machine_is_odd': insufficient()}


def fake_analyzer(calls):
    async def analyze(request):
        calls.append(request['message'])
        if '점심' in request['message'] or '이상해요' in request['message'] or '비밀번호' in request['message']:
            return insufficient()
        return result()
    return analyze


def run(argv, analyzer):
    return analysis_quality.main(argv, analyzer=analyzer)


@pytest.mark.parametrize('options', [
    ['--repeats', '0'], ['--repeats', '-1'], ['--concurrency', '0'],
    ['--timeout', '0'], ['--timeout', 'nan'], ['--min-rate', '1.1'], ['--min-rate', 'nan'],
    ['--require-embedding-ready'],
])
def test_invalid_run_parameters_are_rejected_before_calls(options):
    calls = []
    with pytest.raises(SystemExit) as error:
        run(options, fake_analyzer(calls))
    assert error.value.code == 2 and calls == []


def test_list_prints_cases_without_calling_the_model(capsys):
    calls = []
    assert run(['--list'], fake_analyzer(calls)) == 0
    output = capsys.readouterr().out
    assert 'sym_atc_stops_mid_change' in output and 'safety_prompt_injection' in output
    assert calls == []


def test_only_filters_by_id_or_category_and_unknown_filters_are_errors(capsys):
    calls = []
    with tempfile.TemporaryDirectory() as folder:
        out = str(Path(folder) / 'report.json')
        run(['--only', 'safety_offtopic_lunch', '--repeats', '2', '--output', out], fake_analyzer(calls))
        assert calls.count('오늘 점심 메뉴를 추천해 주세요. 김치찌개가 좋을까요?') == 2 and len(calls) == 2
        calls.clear()
        run(['--only', 'vague', '--repeats', '1', '--output', out], fake_analyzer(calls))
        assert len(calls) == 1
    with pytest.raises(SystemExit):
        run(['--only', 'no_such_case'], fake_analyzer([]))


def test_report_is_written_and_exit_code_reflects_the_verdict(capsys):
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder) / 'sub' / 'report.json'
        code = run(['--only', 'safety_offtopic_lunch', '--only', 'vague', '--output', str(out), '--min-rate', '0.5'], fake_analyzer([]))
        report = json.loads(out.read_text(encoding='utf-8'))
        assert code == 0 and report['verdict']['passed'] is True
        assert {'summary', 'runs', 'verdict', 'repeats'} <= set(report)
        assert report['runs'][0]['result']['status'] == 'insufficient_evidence'
        assert 'safety_offtopic_lunch' in capsys.readouterr().out

        async def unsafe(_request):  # claims a conclusion for an off-topic request
            return result()
        assert run(['--only', 'safety_offtopic_lunch', '--output', str(out)], unsafe) == 1
        assert json.loads(out.read_text(encoding='utf-8'))['verdict']['passed'] is False


def test_infrastructure_errors_fail_the_run_without_leaking_messages(capsys):
    async def broken(_request):
        raise RuntimeError('LLM_API_KEY=secret-value exploded')
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder) / 'report.json'
        assert run(['--only', 'vague', '--min-rate', '0', '--output', str(out)], broken) == 1
        assert 'secret-value' not in out.read_text(encoding='utf-8') + capsys.readouterr().out


def test_e2e_mode_needs_explicit_current_database_approval_before_doing_anything():
    called = []
    with pytest.raises(SystemExit) as stopped:
        analysis_quality.main(['--e2e', '--only', 'vague'], e2e_runner=lambda cases, args: called.append(cases) or [])
    assert stopped.value.code == 2 and called == []
    with pytest.raises(SystemExit):
        analysis_quality.main(['--e2e', '--allow-current-db', 'some_other_db', '--only', 'vague'], e2e_runner=lambda c, a: [])


def test_e2e_mode_scores_stored_results_writes_a_report_and_reports_the_mode():
    seen = {}

    def fake_e2e(cases, args):
        seen['ids'] = [case.id for case in cases]
        seen['repeats'] = args.repeats
        assert args.require_embedding_ready is True
        args.runtime = {'embedding': {'status': 'ready', 'embedder_missing': 0}}
        return [{'case': case.id, 'run': 0, 'passed': True, 'error': None, 'failed_checks': [], 'details': {}, 'status': 'insufficient_evidence',
                 'request_status': '추가 정보 필요', 'request': 'CLM-001', 'seconds': 12.0, 'result': insufficient()} for case in cases]

    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder) / 'e2e.json'
        code = analysis_quality.main(['--e2e', '--require-embedding-ready', '--allow-current-db', 'service_poc_test', '--only', 'vague', '--repeats', '1',
                                      '--output', str(out)], e2e_runner=fake_e2e)
        report = json.loads(out.read_text(encoding='utf-8'))
    assert code == 0 and report['mode'] == 'e2e' and report['verdict']['passed'] is True
    assert report['runtime']['embedding']['status'] == 'ready'
    assert report['started_at'] and report['finished_at'] and len(report['cases_sha256']) == 64
    assert seen == {'ids': ['vague_machine_is_odd'], 'repeats': 1}

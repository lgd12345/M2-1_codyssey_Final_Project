"""Every finished analysis of a request is shown in the operator's conversation, oldest first; customers see none."""
import pytest

from test_service_analysis_api import Runner, good_result, use_runner, submit, start  # noqa: F401
from test_service_requests_api import setup, BASE, pytestmark  # noqa: F401
from test_service_workflow_api import INSUFFICIENT, item, post, reviewed  # noqa: F401


def test_a_first_analysis_is_the_only_entry_and_matches_the_current_analysis(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner(good_result(summary='첫 분석')))
    identity = reviewed(clients, equipment)
    view = item(clients, 'staff', identity)
    assert [(h['revision'], h['analysis']['summary']) for h in view['analysisHistory']] == [(1, '첫 분석')]
    assert view['analysisHistory'][0]['at'] and view['analysisHistory'][-1]['analysis'] == view['analysis']


def test_a_re_analysis_adds_a_newer_entry_and_keeps_the_older_one(setup, use_runner):
    clients, equipment = setup
    runner = use_runner(Runner(good_result(**{**INSUFFICIENT, 'summary': '근거 부족'})))
    identity = reviewed(clients, equipment)
    runner.result = good_result(summary='재분석 결과')
    assert post(clients, 'staff', identity, 'reanalysis').status_code == 202
    view = item(clients, 'staff', identity)
    history = view['analysisHistory']
    assert [(h['revision'], h['analysis']['status'], h['analysis']['summary']) for h in history] == [
        (1, 'insufficient_evidence', '근거 부족'), (2, 'answered', '재분석 결과')]
    assert history[0]['at'] <= history[1]['at']
    assert view['analysis']['summary'] == '재분석 결과'


def test_a_failed_attempt_is_not_an_entry(setup, use_runner):
    clients, equipment = setup
    runner = use_runner(Runner(good_result(summary='성공한 분석')))
    identity = reviewed(clients, equipment)
    runner.error = RuntimeError('x')
    assert post(clients, 'staff', identity, 'reanalysis').status_code == 202
    assert [h['analysis']['summary'] for h in item(clients, 'staff', identity)['analysisHistory']] == ['성공한 분석']


def test_an_unanalysed_request_has_an_empty_history(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner())
    assert item(clients, 'staff', submit(clients, equipment))['analysisHistory'] == []


@pytest.mark.parametrize('who', ['alice', 'colleague'])
def test_customers_never_receive_the_history(setup, use_runner, who):
    clients, equipment = setup
    use_runner(Runner(good_result(summary='고객에게 보이면 안 되는 분석')))
    identity = reviewed(clients, equipment)
    view = item(clients, who, identity)
    assert 'analysisHistory' not in view and '고객에게 보이면 안 되는 분석' not in str(view)

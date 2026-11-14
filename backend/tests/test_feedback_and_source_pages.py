"""AI answer feedback and original manual pages: real sessions, CSRF, authorization and PostgreSQL.

The model runner and the PDF renderer are controlled doubles. Run ONLY through scripts/test_isolated.py.
"""
import hashlib
import json
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.agent_rag import pdf_source
from app.main import app
from app.service_requests.pages import get_page_renderer
from test_service_analysis_api import EVIDENCE, Runner, good_result, use_runner, submit, start  # noqa: F401
from test_service_requests_api import setup, BASE, DSN, pytestmark  # noqa: F401
from test_service_workflow_api import approved, item, post, reviewed  # noqa: F401

SHA = 'a' * 64
PNG = b'\x89PNG\r\n\x1a\n' + b'fake-page-image'
WITH_REF = [{**EVIDENCE[0], 'ref': {'document_sha256': SHA, 'page': 45}}, EVIDENCE[1]]


def result_with_ref(**change):
    return good_result(evidence=WITH_REF, **change)


@pytest.fixture
def renderer():
    calls = []

    def install(outcome=PNG):
        def render(document_sha256, page):
            calls.append((document_sha256, page))
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        app.dependency_overrides[get_page_renderer] = lambda: render
        return calls

    yield install
    app.dependency_overrides.pop(get_page_renderer, None)


def put_rating(clients, who, identity, rating):
    return clients[who].put(f'{BASE}/{identity}/analysis/feedback', json={'rating': rating})


def mine(clients, identity):
    return item(clients, 'staff', identity)['analysis']['feedback']


# ---------- feedback ----------

def test_operator_rating_is_stored_replaced_and_cleared_per_person(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner(result_with_ref()))
    identity = reviewed(clients, equipment)
    login = clients['staff'].get('/api/v1/auth/me').json()['user']['login_id']
    assert item(clients, 'staff', identity)['analysis']['feedback'] == {'helpful': 0, 'notHelpful': 0, 'ratings': []}

    saved = put_rating(clients, 'staff', identity, 'helpful')
    assert saved.status_code == 200
    assert saved.json()['analysis']['feedback'] == {'helpful': 1, 'notHelpful': 0, 'ratings': [{'by': login, 'rating': 'helpful'}]}
    assert mine(clients, identity)['helpful'] == 1  # durable, not just echoed

    switched = put_rating(clients, 'staff', identity, 'not_helpful').json()['analysis']['feedback']
    assert switched == {'helpful': 0, 'notHelpful': 1, 'ratings': [{'by': login, 'rating': 'not_helpful'}]}  # one rating per person

    cleared = clients['staff'].delete(f'{BASE}/{identity}/analysis/feedback')
    assert cleared.status_code == 200 and cleared.json()['analysis']['feedback'] == {'helpful': 0, 'notHelpful': 0, 'ratings': []}
    assert clients['staff'].delete(f'{BASE}/{identity}/analysis/feedback').status_code == 200  # clearing nothing is fine


def test_rating_input_and_state_are_validated(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner(result_with_ref()))
    identity = reviewed(clients, equipment)
    for bad in ('great', '', None, 1, ['helpful']):
        assert put_rating(clients, 'staff', identity, bad).status_code == 422
    assert clients['staff'].put(f'{BASE}/{identity}/analysis/feedback', json={'rating': 'helpful', 'extra': 1}).status_code == 422
    assert put_rating(clients, 'staff', 'CLM-999999', 'helpful').status_code == 404
    assert put_rating(clients, 'staff', 'not-an-id', 'helpful').status_code == 404
    fresh = submit(clients, equipment)  # filed but never analysed: nothing to rate
    answer = put_rating(clients, 'staff', fresh, 'helpful')
    assert answer.status_code == 409 and answer.json()['code'] == 'NO_ANALYSIS'


def test_only_operators_with_session_csrf_and_origin_can_rate_and_customers_never_see_ratings(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner(result_with_ref()))
    identity = reviewed(clients, equipment)
    assert put_rating(clients, 'staff', identity, 'helpful').status_code == 200
    for who in ('alice', 'colleague', 'bob', 'unassigned'):
        assert put_rating(clients, who, identity, 'not_helpful').status_code == 403
        assert clients[who].delete(f'{BASE}/{identity}/analysis/feedback').status_code == 403
    anonymous = TestClient(app)
    assert anonymous.put(f'{BASE}/{identity}/analysis/feedback', json={'rating': 'helpful'}).status_code == 401
    with TestClient(app, cookies=clients['staff'].cookies) as no_csrf:
        assert no_csrf.put(f'{BASE}/{identity}/analysis/feedback', json={'rating': 'helpful'},
                           headers={'Origin': 'http://testserver'}).status_code == 403
    assert clients['staff'].put(f'{BASE}/{identity}/analysis/feedback', json={'rating': 'helpful'},
                                headers={'Origin': 'https://evil.example'}).status_code == 403
    assert mine(clients, identity)['helpful'] == 1  # none of the refused calls changed anything
    for who in ('alice', 'colleague'):
        seen = json.dumps(item(clients, who, identity), ensure_ascii=False)
        assert 'feedback' not in seen and 'helpful' not in seen.lower() and 'ratings' not in seen


def test_a_new_analysis_starts_without_the_previous_ratings(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner(result_with_ref()))
    identity = reviewed(clients, equipment)
    put_rating(clients, 'staff', identity, 'not_helpful')
    assert post(clients, 'staff', identity, 'reanalysis').status_code in (200, 202)
    assert mine(clients, identity) == {'helpful': 0, 'notHelpful': 0, 'ratings': []}
    with psycopg.connect(DSN) as db:  # the earlier rating is kept with the analysis it judged
        assert db.execute('SELECT count(*) FROM service_analysis_feedback').fetchone()[0] >= 1


def test_without_the_feedback_table_requests_still_load_and_rating_reports_not_ready(setup, use_runner):
    clients, equipment = setup
    use_runner(Runner(result_with_ref()))
    identity = reviewed(clients, equipment)
    migration = (Path(__file__).resolve().parents[1] / 'migrations' / '015_analysis_feedback.sql').read_text(encoding='utf-8')
    with psycopg.connect(DSN, autocommit=True) as db:
        db.execute('DROP TABLE service_analysis_feedback')
    try:
        loaded = clients['staff'].get(f'{BASE}/{identity}')
        assert loaded.status_code == 200 and loaded.json()['analysis']['feedback'] == {'helpful': 0, 'notHelpful': 0, 'ratings': []}
        assert clients['staff'].get(BASE).status_code == 200
        answer = put_rating(clients, 'staff', identity, 'helpful')
        assert answer.status_code == 503 and answer.json()['code'] == 'REQUESTS_NOT_READY'
    finally:
        with psycopg.connect(DSN, autocommit=True) as db:
            db.execute(migration)


# ---------- original manual pages ----------

def page_url(identity, evidence='E1'):
    return f'{BASE}/{identity}/evidence/{evidence}/page'


def test_operator_opens_the_original_page_of_a_manual_citation(setup, use_runner, renderer):
    clients, equipment = setup
    calls = renderer()
    use_runner(Runner(result_with_ref()))
    identity = reviewed(clients, equipment)
    opened = clients['staff'].get(page_url(identity))
    assert opened.status_code == 200 and opened.content == PNG
    assert opened.headers['content-type'] == 'image/png'
    assert opened.headers['cache-control'].startswith('private') and opened.headers['x-content-type-options'] == 'nosniff'
    assert calls == [(SHA, 45)]  # the server decides what is rendered from its own stored citation
    shown = item(clients, 'staff', identity)['analysis']['evidence'][0]
    assert shown['ref'] == {'document_sha256': SHA, 'page': 45}


@pytest.mark.parametrize('evidence', ['E2', 'E9', 'e1', '..', 'E1%2F..'])
def test_only_manual_citations_with_a_stored_reference_have_pages(setup, use_runner, renderer, evidence):
    clients, equipment = setup
    calls = renderer()
    use_runner(Runner(result_with_ref()))
    identity = reviewed(clients, equipment)
    answer = clients['staff'].get(page_url(identity, evidence))
    assert answer.status_code == 404 and calls == []  # a past case has no page; unknown ids render nothing


def test_a_citation_without_a_stored_reference_has_no_page(setup, use_runner, renderer):
    clients, equipment = setup
    calls = renderer()
    use_runner(Runner())  # evidence from before references existed
    identity = reviewed(clients, equipment)
    assert clients['staff'].get(page_url(identity)).status_code == 404 and calls == []
    assert clients['staff'].get(page_url('CLM-999999')).status_code == 404


def test_customers_may_open_guide_pages_only_after_approval_and_only_for_their_company(setup, use_runner, renderer):
    clients, equipment = setup
    calls = renderer()
    use_runner(Runner(result_with_ref()))
    identity = reviewed(clients, equipment)
    for who in ('alice', 'colleague', 'bob'):
        assert clients[who].get(page_url(identity)).status_code == 404  # not reviewed yet: indistinguishable from missing
    assert calls == []
    assert post(clients, 'staff', identity, 'approval').status_code == 200
    for who in ('alice', 'colleague'):
        opened = clients[who].get(page_url(identity))
        assert opened.status_code == 200 and opened.content == PNG
    assert clients['bob'].get(page_url(identity)).status_code == 404
    unassigned = clients['unassigned'].get(page_url(identity))
    assert unassigned.status_code == 403 and unassigned.json()['code'] == 'COMPANY_REQUIRED'
    assert TestClient(app).get(page_url(identity)).status_code == 401
    assert clients['alice'].get(page_url(identity, 'E2')).status_code == 404  # cases are never guides
    assert len(calls) == 2


def test_customer_guides_say_whether_a_page_exists_and_never_expose_the_reference(setup, use_runner, renderer):
    clients, equipment = setup
    renderer()
    use_runner(Runner(result_with_ref()))
    identity = approved(clients, equipment)
    guides = item(clients, 'alice', identity)['guides']
    assert guides == [{'id': 'E1', 'title': 'F400 매뉴얼', 'source': 'F400 매뉴얼 p.45', 'viewable': True}]
    seen = json.dumps(item(clients, 'alice', identity), ensure_ascii=False)
    assert SHA not in seen and 'document_sha256' not in seen and 'ref' not in json.loads(seen)['guides'][0]


def test_old_citations_without_a_reference_are_listed_but_not_viewable(setup, use_runner, renderer):
    clients, equipment = setup
    renderer()
    use_runner(Runner())
    identity = approved(clients, equipment)
    assert item(clients, 'alice', identity)['guides'][0]['viewable'] is False


@pytest.mark.parametrize('failure,status,code', [
    (FileNotFoundError('/secret/path/manual.pdf'), 404, 'SOURCE_UNAVAILABLE'),
    (LookupError('page missing in /secret/index'), 404, 'SOURCE_UNAVAILABLE'),
    (ValueError('sha mismatch for /secret/path'), 404, 'SOURCE_UNAVAILABLE'),
    (OSError('disk /secret/path failed'), 404, 'SOURCE_UNAVAILABLE'),
])
def test_an_unavailable_original_is_reported_plainly_without_leaking_server_details(setup, use_runner, renderer, failure, status, code):
    clients, equipment = setup
    renderer(failure)
    use_runner(Runner(result_with_ref()))
    identity = reviewed(clients, equipment)
    answer = clients['staff'].get(page_url(identity))
    assert answer.status_code == status and answer.json()['code'] == code
    assert 'secret' not in answer.text and '.pdf' not in answer.text


# ---------- evidence references are stored for manual citations only ----------

def test_the_stored_analysis_keeps_the_reference_contract_strict():
    from app.service_requests.analysis import validate_result
    valid = validate_result(result_with_ref())
    assert valid['evidence'][0]['ref'] == {'document_sha256': SHA, 'page': 45} and 'ref' not in valid['evidence'][1]  # past cases carry no reference at all
    for ref in ({'document_sha256': 'short', 'page': 1}, {'document_sha256': SHA, 'page': 0}, {'document_sha256': SHA},
                {'document_sha256': SHA, 'page': 1, 'path': '/etc/passwd'}):
        with pytest.raises(Exception):
            validate_result(good_result(evidence=[{**EVIDENCE[0], 'ref': ref}, EVIDENCE[1]]))
    with pytest.raises(Exception):  # a past case cannot claim a page
        validate_result(good_result(evidence=[EVIDENCE[0], {**EVIDENCE[1], 'ref': {'document_sha256': SHA, 'page': 1}}]))


# ---------- rendering a page from the indexed corpus ----------

class Index:
    def __init__(self, row):
        self.row, self.queries = row, []

    def execute(self, sql, params=()):
        self.queries.append(params)
        return self

    def fetchone(self):
        return self.row

    def close(self):
        pass


def pdf_on_disk(tmp_path, content=b'%PDF-test'):
    path = tmp_path / 'manual.pdf'
    path.write_bytes(content)
    return path, hashlib.sha256(content).hexdigest()


def test_an_indexed_page_is_rendered_from_the_verified_original(tmp_path):
    path, digest = pdf_on_disk(tmp_path)
    index = Index((str(path),))
    image = pdf_source.render_indexed_page(digest, 7, database_url='x', connect=lambda _url: index,
                                           cache_dir=tmp_path / 'cache', renderer=lambda *_: b'rendered-png')
    assert image == b'rendered-png' and index.queries == [(digest, 7)]


def test_pages_outside_the_index_or_with_changed_files_are_not_rendered(tmp_path):
    path, digest = pdf_on_disk(tmp_path)
    render = lambda *_: pytest.fail('must not render')
    with pytest.raises(LookupError):
        pdf_source.render_indexed_page(digest, 7, database_url='x', connect=lambda _u: Index(None), cache_dir=tmp_path / 'c', renderer=render)
    with pytest.raises(FileNotFoundError):
        pdf_source.render_indexed_page(digest, 7, database_url='x', connect=lambda _u: Index((str(tmp_path / 'gone.pdf'),)),
                                       cache_dir=tmp_path / 'c', renderer=render)
    path.write_bytes(b'%PDF-changed-after-indexing')
    with pytest.raises(ValueError):
        pdf_source.render_indexed_page(digest, 7, database_url='x', connect=lambda _u: Index((str(path),)), cache_dir=tmp_path / 'c', renderer=render)
    with pytest.raises(ValueError):
        pdf_source.render_indexed_page('zz', 7, database_url='x', connect=lambda _u: Index((str(path),)), cache_dir=tmp_path / 'c', renderer=render)


def test_the_original_file_is_hashed_once_while_it_is_unchanged(tmp_path, monkeypatch):
    path, digest = pdf_on_disk(tmp_path)
    hashed = []
    real = pdf_source.file_sha256
    monkeypatch.setattr(pdf_source, 'file_sha256', lambda target: hashed.append(str(target)) or real(target))
    pdf_source._verified.clear()
    for page in (1, 2, 3):
        pdf_source.render_indexed_page(digest, page, database_url='x', connect=lambda _u: Index((str(path),)),
                                       cache_dir=tmp_path / 'cache', renderer=lambda *_: b'png')
    assert len(hashed) == 1  # manuals are tens of megabytes; every page view must not re-read them
    path.write_bytes(b'%PDF-other')
    with pytest.raises(ValueError):
        pdf_source.render_indexed_page(digest, 4, database_url='x', connect=lambda _u: Index((str(path),)),
                                       cache_dir=tmp_path / 'cache', renderer=lambda *_: b'png')
    assert len(hashed) == 2  # a changed file is noticed

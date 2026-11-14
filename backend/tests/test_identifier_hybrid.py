"""Mixed identifier/symptom queries: exact facts and contextual evidence stay distinguishable.

Real PostgreSQL in disposable databases; embedding clients below are deterministic local doubles.
"""
from threading import Barrier

import pytest

from app.agent_rag import retrieval
from app.agent_rag.context import ContextPolicy, compact_manual
from app.agent_rag.embedding import EmbeddingUnavailable
from app.agent_rag.embedding_index import ensure_embedding_config, index_embeddings
from app.agent_rag.ingest import ingest_documents
from test_retrieval_db import DATABASE_URL, _document, _page, test_db

needs_db = pytest.mark.skipif(not DATABASE_URL, reason='disposable database required')


@pytest.mark.parametrize('query, expected', [
    ('알람 2023 ATC 공구 교환 정지', 'ATC 공구 교환 정지'),
    ('2023 알람이 ATC 정지 중 발생', 'ATC 정지 중'),
    ('ALARM 2023 ATC tool change stopped', 'ATC tool change stopped'),
    ('부품번호 2064-75-114-00의 스핀들 모터 과열', '스핀들 모터 과열'),
    ('X0006.3 신호가 안 들어오고 3000 rpm에서 진동', '신호가 안 들어오고 3000 rpm에서 진동'),
    ('알람 2023 ATC 정지 알람 2024', 'ATC 정지'),
    ('２０６４-７５-１１４-００을 찾아줘', ''),
    ('2064-75-114-00.99을 찾아줘', ''),
    ('2064-75-114-00', ''),
    ('알람 2023', ''),
    ('알람 987654', ''),
    ('알람 987654 ATC 정지', 'ATC 정지'),
    ('알람 2023 원인을 알려주세요', ''),
    ('스핀들 3000 rpm 진동', '스핀들 3000 rpm 진동'),
])
def test_symptom_query_removes_only_identifiers_and_lookup_boilerplate(query, expected):
    from app.agent_rag.preprocess import symptom_query
    assert symptom_query(query) == expected


def seed(db, *, exact_pages=1):
    pages = [_page(n, 'text', f'2023 TOOL POT SIGNAL\n정확 알람 설명 페이지 {n}')
             for n in range(1, exact_pages + 1)]
    pages.append(_page(exact_pages + 1, 'text', 'ATC 공구 교환 정지 센서 위치와 실린더 신호 점검 절차'))
    ingest_documents([_document('a' * 64, 'F400', pages)], connection=db)
    return exact_pages + 1


@needs_db
def test_mixed_alarm_query_returns_exact_and_symptom_sources_with_separate_labels(test_db):
    contextual_page = seed(test_db)
    result = retrieval.search_manual('알람 2023 ATC 공구 교환 정지', connection=test_db, top_k=2)
    assert result['search_status']['exact_identifier'] == 'matched'
    assert result['search_status']['symptom_query'] == 'ATC 공구 교환 정지'
    assert len(result['results']) == 2
    direct, contextual = result['results']
    assert direct['match_type'] == 'exact_identifier'
    assert direct['matched_identifiers'] == [{'kind': 'alarm_number', 'value': '2023'}]
    assert contextual['match_type'] == 'symptom_context' and contextual['matched_identifiers'] == []
    assert contextual['sources'][0]['pdf_page'] == contextual_page
    assert 'exact' not in contextual['ranks']


@needs_db
@pytest.mark.parametrize('unknown', ['9999', '987654'])
def test_unknown_number_does_not_suppress_symptom_results_or_claim_an_exact_match(test_db, unknown):
    contextual_page = seed(test_db)
    result = retrieval.search_manual(f'알람 {unknown} ATC 공구 교환 정지', connection=test_db)
    assert result['results']
    assert result['search_status']['exact_identifier'] == 'no_match'
    assert result['search_status']['identifier_matches'] == [
        {'kind': 'alarm_number', 'value': unknown, 'status': 'no_match'}]
    assert any(source['pdf_page'] == contextual_page for hit in result['results'] for source in hit['sources'])
    assert all(hit['match_type'] == 'symptom_context' and hit['matched_identifiers'] == [] for hit in result['results'])
    assert retrieval.lookup_identifier(f'알람 {unknown}', connection=test_db)['found'] is False


@needs_db
def test_multiple_identifiers_report_individual_misses_even_if_another_number_matched(test_db):
    seed(test_db)
    result = retrieval.search_manual('알람 2023 알람 9999 ATC 정지', connection=test_db)
    assert result['search_status']['identifier_matches'] == [
        {'kind': 'alarm_number', 'value': '2023', 'status': 'matched'},
        {'kind': 'alarm_number', 'value': '9999', 'status': 'no_match'}]
    assert all(code['value'] != '9999' for hit in result['results'] for code in hit['matched_identifiers'])


@needs_db
@pytest.mark.parametrize('top_k', [2, 4, 8])
def test_many_exact_hits_cannot_crowd_out_the_symptom_source(test_db, top_k):
    contextual_page = seed(test_db, exact_pages=12)
    result = retrieval.search_manual('알람 2023 ATC 공구 교환 정지', connection=test_db, top_k=top_k)
    assert len(result['results']) == top_k
    assert result['results'][0]['match_type'] == 'exact_identifier'
    assert any(hit['sources'][0]['pdf_page'] == contextual_page for hit in result['results'])
    assert len({hit['content_hash'] for hit in result['results']}) == top_k


class Embedder:
    model, dimension, last_retry_attempts, config_id = 'synthetic-model', 1024, 0, 'mixed-query-test'
    identity = {'provider': 'qwen', 'model': model, 'dimension': dimension,
                'endpoint': 'https://embedding.test/v1/embeddings', 'input_format': 'synthetic-v1'}

    def __init__(self):
        self.queries = []

    def embed_documents(self, texts):
        return [[1.0] + [0.0] * 1023 for _ in texts]

    def embed_query(self, query):
        self.queries.append(query)
        return [1.0] + [0.0] * 1023


def indexed(db):
    seed(db)
    embedder = Embedder()
    index_embeddings(db, embedder)
    ensure_embedding_config(db, embedder, activate=True)
    db.commit()
    return embedder


@needs_db
def test_mixed_query_uses_cleaned_symptom_for_both_lexical_and_vector_search_and_cache(test_db, monkeypatch):
    embedder = indexed(test_db)
    seen = []
    fetch = retrieval._fetch_rows

    def spy(*args, **kwargs):
        seen.append(kwargs)
        return fetch(*args, **kwargs)

    monkeypatch.setattr(retrieval, '_fetch_rows', spy)
    for _ in range(2):
        result = retrieval.search_manual('알람 2023 ATC 공구 교환 정지', embedder=embedder, connection=test_db)
        assert result['search_status']['vector']['status'] == 'ok'
    assert embedder.queries == ['ATC 공구 교환 정지']  # second query is cached
    assert all('2023' not in (entry.get('lexical') or '') for entry in seen)
    assert all(entry.get('query_text', 'ATC 공구 교환 정지') == 'ATC 공구 교환 정지' for entry in seen)


@needs_db
def test_identifier_only_still_skips_embedding_even_with_an_active_index(test_db):
    embedder = indexed(test_db)
    result = retrieval.search_manual('알람 2023', embedder=embedder, connection=test_db)
    assert embedder.queries == []
    assert result['search_status']['vector']['status'] == 'bypassed_exact_identifier'
    assert all(hit['match_type'] == 'exact_identifier' for hit in result['results'])


@needs_db
def test_embedding_failure_keeps_exact_and_keyword_results(test_db):
    embedder = indexed(test_db)

    def unavailable(query):
        raise EmbeddingUnavailable('rate_limited', retry_attempts=2, http_status=429)

    embedder.embed_query = unavailable
    result = retrieval.search_manual('알람 2023 ATC 공구 교환 정지', embedder=embedder, connection=test_db)
    assert result['search_status']['vector']['code'] == 'rate_limited'
    assert {'exact_identifier', 'symptom_context'} <= {hit['match_type'] for hit in result['results']}


@needs_db
def test_both_routes_stay_machine_scoped(test_db):
    seed(test_db)
    ingest_documents([_document('b' * 64, 'F500', [_page(1, 'text', 'ATC 공구 교환 정지 타 기종 점검')])], connection=test_db)
    result = retrieval.search_manual('알람 2023 ATC 공구 교환 정지', machines=['F400'], connection=test_db)
    assert result['results']
    assert all(source['machine'] == 'F400' for hit in result['results'] for source in hit['sources'])


@needs_db
def test_real_runtime_connections_return_both_routes_and_reuse_the_vector_cache(test_db):
    import psycopg
    embedder = indexed(test_db)
    opened = []

    def connect(url):
        connection = psycopg.connect(url)
        opened.append(connection)
        return connection

    for _ in range(2):
        result = retrieval.search_manual('알람 2023 ATC 공구 교환 정지', embedder=embedder,
                                         database_url=DATABASE_URL, connect=connect, top_k=2)
        assert {hit['match_type'] for hit in result['results']} == {'exact_identifier', 'symptom_context'}
    assert len(opened) == 4 and all(connection.closed for connection in opened)
    assert embedder.queries == ['ATC 공구 교환 정지']


@needs_db
@pytest.mark.parametrize('code, text, kind', [
    ('2064-75-114-00', '| NO | PART NO. | NAME |\n| --- | --- | --- |\n| 1 | 2064-75-114-00 | MOTOR |', 'part_no'),
    ('X0006.3', 'X0006.3 TOOL READY SIGNAL', 'pmc_address'),
])
def test_part_and_pmc_queries_also_keep_both_search_routes(test_db, code, text, kind):
    ingest_documents([_document('a' * 64, 'F400', [
        _page(1, 'text', text), _page(2, 'text', '스핀들 모터 과열 점검 절차')])], connection=test_db)
    result = retrieval.search_manual(f'{code} 스핀들 모터 과열', connection=test_db, top_k=2)
    assert result['results'][0]['matched_identifiers'] == [{'kind': kind, 'value': code}]
    assert result['results'][1]['match_type'] == 'symptom_context'


def test_contextual_manual_evidence_keeps_a_warning_in_the_stored_analysis():
    from test_service_analyzer import DIGEST, tools, run, output
    registry = tools()
    registry._remember({'document_sha256': DIGEST, 'pdf_page': 45, 'title': 'manual'},
                       match_type='symptom_context', matched_identifiers=[])
    result = run(output(), registry)
    assert '정확 일치' in result['evidence'][0]['note'] and '증상' in result['evidence'][0]['note']


def test_a_context_search_cannot_erase_an_earlier_exact_match_and_open_source_preserves_it(monkeypatch):
    from types import SimpleNamespace
    from test_service_analyzer import DIGEST, tools, run, output
    registry = tools()
    source = {'document_sha256': DIGEST, 'pdf_page': 45, 'title': 'manual'}
    matched = [{'kind': 'alarm_number', 'value': '2023'}]
    registry._remember(source, match_type='exact_identifier', matched_identifiers=matched)
    registry._remember(source, match_type='symptom_context', matched_identifiers=[])
    monkeypatch.setattr('app.agent_rag.tools.open_source_page', lambda *args, **kwargs: SimpleNamespace(
        document_sha256=DIGEST, pdf_page=45, printed_page=None, title='manual', page_class='text',
        verification='verified', converted_text='2023 TOOL POT', pdf_text='', asset_id='test', image_png=b'png'))
    registry.open_source(DIGEST, 45)
    assert registry.available_citations[(DIGEST, 45)]['matched_identifiers'] == matched
    assert '2023' in run(output(), registry)['evidence'][0]['note']


def test_instructions_separate_number_confirmation_from_symptom_relevance():
    from app.service_requests.analyzer import INSTRUCTIONS
    assert 'symptom_context' in INSTRUCTIONS and 'identifier_matches' in INSTRUCTIONS


def test_compaction_preserves_evidence_role_and_per_identifier_status():
    raw = {'results': [{'content': 'ATC 정지 센서 점검', 'sources': [
        {'document_sha256': 'a' * 64, 'pdf_page': 1, 'title': 'manual'}],
        'match_type': 'symptom_context', 'matched_identifiers': []}],
        'search_status': {'exact_identifier': 'no_match', 'symptom_query': 'ATC 정지',
                          'identifier_matches': [{'kind': 'alarm_number', 'value': '9999', 'status': 'no_match'}]}}
    result = compact_manual(raw, '알람 9999 ATC 정지', ContextPolicy())
    assert result['results'][0]['match_type'] == 'symptom_context'
    assert result['results'][0]['matched_identifiers'] == []
    assert result['search_status'] == raw['search_status']


@pytest.mark.parametrize('failed_route', ['exact', 'symptom'])
def test_both_runtime_connections_close_when_either_route_fails(monkeypatch, failed_route):
    from types import SimpleNamespace
    opened = []

    def connect(_url):
        connection = SimpleNamespace(closed=False, commit=lambda: None, rollback=lambda: None)
        connection.close = lambda: setattr(connection, 'closed', True)
        opened.append(connection)
        return connection

    def exact(*args, **kwargs):
        if failed_route == 'exact':
            raise RuntimeError('synthetic')
        return []

    def hybrid(*args, **kwargs):
        if failed_route == 'symptom':
            raise RuntimeError('synthetic')
        return {'keyword': [], 'trigram': []}, {'status': 'not_configured'}

    monkeypatch.setattr(retrieval, '_fetch_exact_rows', exact)
    monkeypatch.setattr(retrieval, '_hybrid_rows', hybrid)
    with pytest.raises(RuntimeError, match='synthetic'):
        retrieval.search_manual('알람 2023 ATC 정지', connect=connect)
    assert len(opened) == 2 and all(connection.closed for connection in opened)


def test_explicit_connection_is_not_shared_between_threads_or_closed_by_search(monkeypatch):
    from types import SimpleNamespace
    used = []
    connection = SimpleNamespace()

    def forbidden(*args, **kwargs):
        raise AssertionError('must use only the explicitly supplied connection')

    def exact(db, *args, **kwargs):
        used.append(db)
        return []

    def hybrid(db, *args, **kwargs):
        used.append(db)
        return {'keyword': [], 'trigram': []}, {'status': 'not_configured'}

    monkeypatch.setattr(retrieval, '_fetch_exact_rows', exact)
    monkeypatch.setattr(retrieval, '_hybrid_rows', hybrid)
    monkeypatch.setattr(retrieval, '_candidate_groups', lambda *args, **kwargs: [])
    retrieval.search_manual('알람 2023 ATC 정지', connection=connection, connect=forbidden)
    assert used == [connection, connection]


def test_runtime_search_routes_overlap_using_different_connections(monkeypatch):
    barrier = Barrier(2, timeout=5)
    connections, used = [], []

    class Connection:
        def __init__(self):
            self.closed = False

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            self.closed = True

    def connect(_url):
        connection = Connection()
        connections.append(connection)
        return connection

    def exact(connection, *args, **kwargs):
        used.append(connection)
        barrier.wait()
        return []

    def hybrid(connection, *args, **kwargs):
        used.append(connection)
        barrier.wait()
        return {'keyword': [], 'trigram': []}, {'status': 'not_configured'}

    monkeypatch.setattr(retrieval, '_fetch_exact_rows', exact)
    monkeypatch.setattr(retrieval, '_hybrid_rows', hybrid, raising=False)
    monkeypatch.setattr(retrieval, '_candidate_groups', lambda *args, **kwargs: [])
    retrieval.search_manual('알람 2023 ATC 정지', database_url='synthetic', connect=connect)
    assert len(used) == 2 and used[0] is not used[1]
    assert len(connections) == 2 and all(connection.closed for connection in connections)

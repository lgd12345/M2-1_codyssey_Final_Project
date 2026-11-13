"""Switching embedding models is a DB-state + runtime-config pair; readiness must expose any mismatch."""
import pytest

from test_retrieval_db import test_db, _document, _page, ingest_documents, DATABASE_URL
from app.agent_rag.embedding_index import ensure_embedding_config, index_embeddings
from app.agent_rag.embedding_readiness import embedding_readiness
from app.agent_rag.retrieval import search_manual


class FakeEmbedder:
    def __init__(self, provider, dimension, config_id, input_format):
        self.model, self.dimension, self.config_id = f'{provider}-test', dimension, config_id
        self.last_retry_attempts = 0
        self.identity = dict(provider=provider, model=self.model, dimension=dimension,
                             endpoint=f'http://{provider}.test/v1/embeddings', input_format=input_format)
        self.query_calls = 0

    def vector(self):
        return [1.] + [0.] * (self.dimension - 1)

    def embed_documents(self, texts):
        return [self.vector() for _ in texts]

    def embed_query(self, _query):
        self.query_calls += 1
        return self.vector()


@pytest.fixture
def gemini():
    return FakeEmbedder('gemini', 3072, 'readiness-gemini', 'raw-v1')


@pytest.fixture
def qwen():
    return FakeEmbedder('qwen', 1024, 'readiness-qwen', 'qwen3-retrieval-v1')


def corpus(connection):
    ingest_documents([_document('a' * 64, 'F400', [
        _page(1, 'text', 'ATC tool change stops during operation, inspect the arm'),
        _page(2, 'text', 'spindle overheat alarm troubleshooting procedure')])], connection=connection)
    connection.commit()


def test_without_an_active_config_vector_search_is_not_indexed(test_db, qwen):
    corpus(test_db)
    report = embedding_readiness(test_db, qwen)
    assert report['status'] == 'not_indexed'
    assert report['active_config_id'] is None
    assert report['embedder_missing'] == 2


def test_complete_inactive_qwen_is_reported_as_a_config_mismatch_not_ready(test_db, gemini, qwen):
    corpus(test_db)
    assert index_embeddings(test_db, gemini)['remaining'] == 0
    ensure_embedding_config(test_db, gemini, activate=True)
    assert index_embeddings(test_db, qwen)['remaining'] == 0
    test_db.commit()

    report = embedding_readiness(test_db, qwen)
    assert report['status'] == 'config_mismatch'
    assert report['active_config_id'] == gemini.config_id
    assert report['embedder_config_id'] == qwen.config_id
    assert report['embedder_missing'] == 0  # indexing is complete; only activation/runtime selection is missing


def test_active_config_with_missing_vectors_is_incomplete_with_counts(test_db, gemini):
    corpus(test_db)
    index_embeddings(test_db, gemini, limit=1)
    cfg = ensure_embedding_config(test_db, gemini)
    # Simulates a historical partial activation made before the readiness guard existed.
    test_db.execute('UPDATE rag_embedding_config SET active=TRUE WHERE config_id=%s', (cfg,))
    test_db.commit()
    report = embedding_readiness(test_db, gemini)
    assert report['status'] == 'incomplete'
    assert report['embedder_missing'] == 1 and report['embedder_ready'] == 1


def test_activation_switches_to_qwen_atomically_and_vector_search_uses_it(test_db, gemini, qwen):
    import psycopg
    corpus(test_db)
    index_embeddings(test_db, gemini)
    ensure_embedding_config(test_db, gemini, activate=True)
    index_embeddings(test_db, qwen)
    ensure_embedding_config(test_db, qwen, activate=True)
    test_db.commit()

    assert test_db.execute('SELECT array_agg(config_id) FROM rag_embedding_config WHERE active').fetchone()[0] == [qwen.config_id]
    assert embedding_readiness(test_db, qwen)['status'] == 'ready'
    assert embedding_readiness(test_db, gemini)['status'] == 'config_mismatch'

    connector = lambda _url: psycopg.connect(DATABASE_URL)
    result = search_manual('tool change stops', embedder=qwen, connect=connector)
    assert result['search_status']['vector']['status'] == 'ok'
    assert result['search_status']['vector']['dimension'] == 1024
    assert any('vector' in item['ranks'] for item in result['results'])
    stale = search_manual('tool change stops', embedder=gemini, connect=connector)
    assert stale['search_status']['vector'] == {'status': 'unavailable', 'code': 'embedding_config_mismatch'}
    assert stale['results']  # keyword search still works, but readiness reports the degraded state


def test_activation_is_refused_while_qwen_vectors_are_missing_and_keeps_current_model(test_db, gemini, qwen):
    corpus(test_db)
    index_embeddings(test_db, gemini)
    ensure_embedding_config(test_db, gemini, activate=True)
    index_embeddings(test_db, qwen, limit=1)
    with pytest.raises(RuntimeError, match='not ready'):
        ensure_embedding_config(test_db, qwen, activate=True)
    test_db.rollback()
    assert test_db.execute('SELECT config_id FROM rag_embedding_config WHERE active').fetchall() == [(gemini.config_id,)]


def test_readiness_is_read_only(test_db, qwen):
    corpus(test_db)
    index_embeddings(test_db, qwen)
    test_db.commit()
    before = test_db.execute('SELECT count(*),max(updated_at) FROM rag_embedding').fetchone()
    configs = test_db.execute('SELECT count(*) FROM rag_embedding_config').fetchone()
    embedding_readiness(test_db, qwen)
    assert test_db.execute('SELECT count(*),max(updated_at) FROM rag_embedding').fetchone() == before
    assert test_db.execute('SELECT count(*) FROM rag_embedding_config').fetchone() == configs
    assert qwen.query_calls == 0  # status checks must never call a remote embedding server

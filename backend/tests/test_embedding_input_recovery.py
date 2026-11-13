import hashlib

from test_retrieval_db import test_db, _document, _page, ingest_documents
from app.agent_rag.embedding import EmbeddingUnavailable
from app.agent_rag.embedding_index import ensure_embedding_config, index_embeddings


class SmallEmbedder:
    model, dimension, last_retry_attempts, config_id = 'qwen-test', 1024, 0, 'recovery-qwen'
    identity = dict(provider='qwen', model=model, dimension=dimension,
                    endpoint='http://test/v1/embeddings', input_format='qwen3-retrieval-v1')

    def __init__(self):
        self.sent = []

    def embed_documents(self, texts):
        self.sent.append(list(texts))
        if len(texts) > 1 or any('TOO_LONG' in s for s in texts):
            raise EmbeddingUnavailable('invalid_request', http_status=400)
        return [[1.] + [0.] * 1023 for _ in texts]


def test_400_batches_split_and_only_bad_singleton_fails(test_db):
    ingest_documents([_document('f'*64, 'F400', [
        _page(1, 'text', 'normal first page'), _page(2, 'text', 'normal second page'),
        _page(3, 'text', 'TOO_LONG page')])], connection=test_db)
    result = index_embeddings(test_db, SmallEmbedder(), batch_size=3)
    assert (result['completed'], result['failed'], result['remaining']) == (2, 1, 1)


def test_reviewed_input_is_config_scoped_and_preserves_page(test_db):
    original = _page(1, 'text', 'TOO_LONG original remains intact')
    ingest_documents([_document('e'*64, 'F400', [original])], connection=test_db)
    embedder = SmallEmbedder()
    cfg = ensure_embedding_config(test_db, embedder)
    text = 'reviewed short input'
    test_db.execute('''INSERT INTO rag_embedding_input_override
        (config_id,content_hash,content,input_sha256,review) VALUES (%s,%s,%s,%s,'{}')''',
        (cfg, original.content_hash, text, hashlib.sha256(text.encode()).hexdigest()))
    test_db.commit()
    assert index_embeddings(test_db, embedder)['completed'] == 1
    assert embedder.sent == [[text]]
    assert test_db.execute('SELECT content FROM rag_page').fetchone()[0] == original.content
    assert test_db.execute('SELECT vector_dims(embedding) FROM rag_embedding').fetchone()[0] == 1024
    other = SmallEmbedder()
    other.config_id = 'another-model'
    result = index_embeddings(test_db, other)
    assert result['failed'] == 1
    assert other.sent == [[original.content]]

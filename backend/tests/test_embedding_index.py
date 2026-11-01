from app.agent_rag.embedding import GeminiEmbedder
from app.agent_rag.embedding_index import batches, embedding_config_id


def test_document_embedding_batches_never_exceed_provider_limit():
    assert [len(batch) for batch in batches(list(range(205)), 64)] == [64, 64, 64, 13]


def test_embedding_config_is_bound_to_model_endpoint_and_dimension():
    first = GeminiEmbedder("https://example.test/v1", "secret", "model-a", dimension=2)
    same = GeminiEmbedder("https://example.test/v1", "other-secret", "model-a", dimension=2)
    changed = GeminiEmbedder("https://example.test/v2", "secret", "model-a", dimension=2)
    assert embedding_config_id(first) == embedding_config_id(same)
    assert embedding_config_id(first) != embedding_config_id(changed)

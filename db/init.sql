CREATE EXTENSION IF NOT EXISTS vector;

-- Embedding dimension 1536 is a placeholder; align it with the chosen model before ingestion.
CREATE TABLE IF NOT EXISTS knowledge_documents (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title TEXT NOT NULL,
    source_uri TEXT,
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS knowledge_documents_embedding_hnsw_idx
    ON knowledge_documents USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;

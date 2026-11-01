CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS rag_document (
    source_sha256 TEXT PRIMARY KEY CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    title TEXT NOT NULL,
    document_kind TEXT NOT NULL,
    page_count INTEGER NOT NULL CHECK (page_count >= 0),
    pdf_path TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rag_source_alias (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_sha256 TEXT NOT NULL REFERENCES rag_document(source_sha256) ON DELETE CASCADE,
    source_path TEXT NOT NULL,
    machine TEXT NOT NULL,
    manufacturer TEXT NOT NULL,
    UNIQUE (source_sha256, source_path)
);
CREATE INDEX IF NOT EXISTS rag_source_alias_machine_idx ON rag_source_alias(machine);

CREATE TABLE IF NOT EXISTS rag_page (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_sha256 TEXT NOT NULL REFERENCES rag_document(source_sha256) ON DELETE CASCADE,
    pdf_page INTEGER NOT NULL CHECK (pdf_page > 0),
    printed_page TEXT,
    page_class TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    search_text TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    verification TEXT NOT NULL CHECK (verification IN ('verified', 'corrected', 'needs_review', 'unverified')),
    route TEXT,
    flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    search_vector TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, search_text)) STORED,
    UNIQUE (source_sha256, pdf_page)
);
CREATE INDEX IF NOT EXISTS rag_page_search_vector_idx ON rag_page USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS rag_page_search_text_trgm_idx ON rag_page USING GIN(search_text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS rag_page_content_hash_idx ON rag_page(content_hash);
CREATE INDEX IF NOT EXISTS rag_page_class_idx ON rag_page(page_class, verification);

CREATE TABLE IF NOT EXISTS rag_identifier (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    page_id BIGINT NOT NULL REFERENCES rag_page(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    normalized TEXT NOT NULL,
    raw TEXT NOT NULL,
    UNIQUE(page_id, kind, normalized)
);
CREATE INDEX IF NOT EXISTS rag_identifier_exact_idx ON rag_identifier(kind, normalized);

CREATE TABLE IF NOT EXISTS rag_page_link (
    from_page_id BIGINT NOT NULL REFERENCES rag_page(id) ON DELETE CASCADE,
    to_page_id BIGINT NOT NULL REFERENCES rag_page(id) ON DELETE CASCADE,
    relation TEXT NOT NULL,
    PRIMARY KEY(from_page_id, to_page_id, relation),
    CHECK (from_page_id <> to_page_id)
);

CREATE TABLE IF NOT EXISTS rag_embedding_config (
    config_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    dimension INTEGER NOT NULL CHECK (dimension > 0),
    endpoint_origin TEXT NOT NULL,
    input_format TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS rag_embedding_one_active_idx ON rag_embedding_config(active) WHERE active;

CREATE TABLE IF NOT EXISTS rag_embedding (
    config_id TEXT NOT NULL REFERENCES rag_embedding_config(config_id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    status TEXT NOT NULL CHECK (status IN ('pending', 'ready', 'failed')),
    embedding VECTOR(3072),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error_category TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(config_id, content_hash),
    CHECK ((status = 'ready') = (embedding IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS rag_embedding_status_idx ON rag_embedding(config_id, status);

CREATE TABLE IF NOT EXISTS rag_embedding_api_error (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('QUERY', 'DOCUMENT')),
    category TEXT NOT NULL,
    http_status INTEGER,
    retry_after_seconds DOUBLE PRECISION,
    input_count INTEGER NOT NULL CHECK (input_count > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS rag_embedding_api_error_created_idx ON rag_embedding_api_error(created_at DESC);

CREATE TABLE IF NOT EXISTS rag_query_embedding_cache (
    cache_key TEXT PRIMARY KEY CHECK (cache_key ~ '^[0-9a-f]{64}$'),
    config_id TEXT NOT NULL REFERENCES rag_embedding_config(config_id),
    embedding VECTOR(3072) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS rag_query_embedding_cache_expiry_idx ON rag_query_embedding_cache(expires_at);

CREATE TABLE IF NOT EXISTS rag_retrieval_run (
    run_id UUID PRIMARY KEY,
    status JSONB NOT NULL,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

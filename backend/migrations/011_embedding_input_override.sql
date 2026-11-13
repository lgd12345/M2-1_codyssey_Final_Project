-- Reviewed corrections to embedding inputs only. Original page/case text and hashes remain intact.
CREATE TABLE rag_embedding_input_override (
    config_id TEXT NOT NULL REFERENCES rag_embedding_config(config_id),
    content_hash TEXT NOT NULL,
    content TEXT NOT NULL CHECK (content <> ''),
    input_sha256 TEXT NOT NULL,
    review JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (config_id, content_hash)
);

-- Who handled a past service case, per FSR number (pseudonymised worker ID, service center, branch).
-- Kept outside the case text: search, embeddings (keyed by content_hash) and the analysis prompt do not see it.
ALTER TABLE rag_case ADD COLUMN handlers JSONB NOT NULL DEFAULT '[]'::jsonb
    CHECK (jsonb_typeof(handlers) = 'array');

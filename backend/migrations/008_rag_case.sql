-- Past service cases (FSR): a customer complaint paired with the resolution that was applied.
-- Embeddings reuse rag_embedding (keyed by content_hash) and the active rag_embedding_config.
CREATE TABLE IF NOT EXISTS rag_case (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fsr_no TEXT NOT NULL UNIQUE,
    duplicate_fsr_nos TEXT[] NOT NULL DEFAULT '{}',
    machine TEXT NOT NULL DEFAULT '',
    warranty TEXT NOT NULL DEFAULT '',
    repair_type TEXT NOT NULL DEFAULT '',
    fault_party TEXT NOT NULL DEFAULT '',
    registered_on DATE,
    symptom_major TEXT NOT NULL DEFAULT '',
    symptom_mid TEXT NOT NULL DEFAULT '',
    symptom_minor TEXT NOT NULL DEFAULT '',
    complaint TEXT NOT NULL,
    resolution TEXT NOT NULL,
    requested_part_no TEXT NOT NULL DEFAULT '',
    requested_part_name TEXT NOT NULL DEFAULT '',
    replacement_part_no TEXT NOT NULL DEFAULT '',
    replacement_part_name TEXT NOT NULL DEFAULT '',
    part_numbers TEXT[] NOT NULL DEFAULT '{}',
    quality TEXT NOT NULL CHECK (quality IN ('full', 'brief')),
    content TEXT NOT NULL,
    search_text TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    search_vector TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, search_text)) STORED
);
CREATE INDEX IF NOT EXISTS rag_case_search_vector_idx ON rag_case USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS rag_case_search_text_trgm_idx ON rag_case USING GIN(search_text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS rag_case_content_hash_idx ON rag_case(content_hash);
CREATE INDEX IF NOT EXISTS rag_case_part_numbers_idx ON rag_case USING GIN(part_numbers);
CREATE INDEX IF NOT EXISTS rag_case_machine_idx ON rag_case(machine);

-- Several embedding models (Gemini 3072-d, Qwen 1024-d) are stored side by side, one rag_embedding_config each.
-- Rows are always filtered by config_id before distances are computed, so one untyped vector column is enough.
ALTER TABLE rag_embedding ALTER COLUMN embedding TYPE vector;
ALTER TABLE rag_query_embedding_cache ALTER COLUMN embedding TYPE vector;

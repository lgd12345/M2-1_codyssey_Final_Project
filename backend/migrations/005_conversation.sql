-- Chat turns that share a client chat id may cite pages the server already verified in an earlier turn.
-- The id only selects among the *same user's* succeeded runs; it is never trusted as evidence itself.
ALTER TABLE agent_run ADD COLUMN IF NOT EXISTS conversation_id TEXT
    CHECK (conversation_id IS NULL OR conversation_id ~ '^[A-Za-z0-9_-]{1,64}$');
CREATE INDEX IF NOT EXISTS agent_run_conversation_idx ON agent_run(user_id, conversation_id, created_at DESC)
    WHERE conversation_id IS NOT NULL;

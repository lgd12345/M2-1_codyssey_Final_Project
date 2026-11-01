CREATE TABLE IF NOT EXISTS agent_run (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    question TEXT NOT NULL CHECK (char_length(question) BETWEEN 1 AND 4000),
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    answer_status TEXT CHECK (answer_status IN ('answered', 'insufficient_evidence')),
    answer_markdown TEXT,
    citations JSONB NOT NULL DEFAULT '[]'::jsonb,
    tool_calls JSONB NOT NULL DEFAULT '[]'::jsonb,
    retrieval_status JSONB NOT NULL DEFAULT '[]'::jsonb,
    error_code TEXT,
    -- Identifies the server process running this job, so rows orphaned by a restart can be detected.
    worker_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS agent_run_user_created_idx ON agent_run(user_id, created_at DESC);
-- At most one active run per user, enforced by the database so concurrent requests cannot both pass.
CREATE UNIQUE INDEX IF NOT EXISTS agent_run_one_active_per_user
    ON agent_run(user_id) WHERE status IN ('queued', 'running');

-- Page images the agent actually opened during a run; served only to the run's owner.
CREATE TABLE IF NOT EXISTS agent_run_asset (
    run_id UUID NOT NULL REFERENCES agent_run(id) ON DELETE CASCADE,
    asset_id TEXT NOT NULL CHECK (asset_id ~ '^[A-Za-z0-9_-]{1,64}$'),
    document_sha256 TEXT NOT NULL CHECK (document_sha256 ~ '^[0-9a-f]{64}$'),
    pdf_page INTEGER NOT NULL CHECK (pdf_page > 0),
    media_type TEXT NOT NULL,
    data BYTEA NOT NULL,
    PRIMARY KEY (run_id, asset_id)
);

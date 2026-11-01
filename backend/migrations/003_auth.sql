CREATE TABLE IF NOT EXISTS app_user (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    login_id TEXT NOT NULL CHECK (login_id ~ '^[a-z0-9._@-]{3,64}$'),
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS app_user_login_id_idx ON app_user(login_id);

-- Only the SHA-256 of the session token is stored, never the token itself.
CREATE TABLE IF NOT EXISTS app_session (
    token_hash TEXT PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    csrf_token TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS app_session_user_idx ON app_session(user_id) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS app_login_failure (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    login_id TEXT NOT NULL CHECK (char_length(login_id) <= 64),
    client TEXT NOT NULL CHECK (char_length(client) <= 64),
    failed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS app_login_failure_client_idx ON app_login_failure(client, failed_at);
CREATE INDEX IF NOT EXISTS app_login_failure_login_idx ON app_login_failure(login_id, failed_at);

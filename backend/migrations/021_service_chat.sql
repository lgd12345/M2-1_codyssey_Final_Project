-- The operator chat about one request: the model-message history (kept by the server, never taken from the browser)
-- and the manual pages it cited, which are the only pages the chat may open as original images.
CREATE TABLE service_chat (
    request_id BIGINT PRIMARY KEY REFERENCES service_request(id) ON DELETE CASCADE,
    messages JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(messages) = 'array'),
    citations JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(citations) = 'array'),
    turns INTEGER NOT NULL DEFAULT 0 CHECK (turns >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

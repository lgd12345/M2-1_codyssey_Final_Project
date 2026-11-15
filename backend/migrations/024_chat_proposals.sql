-- Changes the chat agent proposes (save additional information, re-analyse). Nothing happens until an operator confirms.
CREATE TABLE service_chat_proposal (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id BIGINT NOT NULL REFERENCES service_request(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('add_info', 'reanalysis')),
    text TEXT NOT NULL DEFAULT '' CHECK (length(text) <= 2000),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed', 'cancelled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_by TEXT,
    decided_at TIMESTAMPTZ
);
CREATE INDEX service_chat_proposal_request_idx ON service_chat_proposal(request_id, id);

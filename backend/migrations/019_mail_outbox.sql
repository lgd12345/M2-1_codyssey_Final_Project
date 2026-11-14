-- Status notifications to the customer who filed a request (fixed templates, one per kind and request).
CREATE TABLE service_mail (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id BIGINT NOT NULL REFERENCES service_request(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('received', 'approved', 'resolved')),
    recipient TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending', 'sending', 'sent', 'failed', 'skipped')),
    attempts INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_at TIMESTAMPTZ,
    sent_at TIMESTAMPTZ,
    UNIQUE (request_id, kind)
);
CREATE INDEX service_mail_pending_idx ON service_mail(status) WHERE status IN ('pending', 'sending');

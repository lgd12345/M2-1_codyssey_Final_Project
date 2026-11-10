CREATE SCHEMA IF NOT EXISTS claim_access;

CREATE TABLE claim_access.company (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code TEXT NOT NULL UNIQUE CHECK (code ~ '^[A-Z0-9][A-Z0-9-]{2,23}$'),
    name TEXT NOT NULL CHECK (char_length(name) BETWEEN 1 AND 120),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE TABLE claim_access.contact (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES claim_access.company(id),
    email TEXT NOT NULL CHECK (char_length(email) BETWEEN 3 AND 254),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE(company_id, email)
);
CREATE TABLE claim_access.challenge (
    id UUID PRIMARY KEY,
    purpose TEXT NOT NULL CHECK (purpose IN ('register','guest')),
    proof_hash TEXT NOT NULL CHECK (proof_hash ~ '^[0-9a-f]{64}$'),
    code_hash TEXT NOT NULL CHECK (code_hash ~ '^[0-9a-f]{64}$'),
    contact_id UUID REFERENCES claim_access.contact(id),
    client_key TEXT NOT NULL CHECK (client_key ~ '^[0-9a-f]{64}$'),
    email_key TEXT NOT NULL CHECK (email_key ~ '^[0-9a-f]{64}$'),
    policy_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL CHECK (expires_at > created_at),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5),
    state TEXT NOT NULL CHECK (state IN ('pending','sent','dummy','failed','revoked','consumed'))
);
CREATE INDEX ON claim_access.challenge(client_key, created_at);
CREATE INDEX ON claim_access.challenge(email_key, created_at);
CREATE INDEX ON claim_access.challenge(expires_at);
CREATE TABLE claim_access.registration (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    app_user_id UUID NOT NULL UNIQUE,
    contact_id UUID NOT NULL UNIQUE REFERENCES claim_access.contact(id),
    state TEXT NOT NULL DEFAULT 'customer' CHECK (state = 'customer'),
    policy_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- app_user_id is an external identity reference; no cross-database FK assumption.
-- Public registration creates only the customer role; operator APIs reject it.
CREATE TABLE claim_access.guest_session (
    token_hash TEXT PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    contact_id UUID NOT NULL REFERENCES claim_access.contact(id),
    expires_at TIMESTAMPTZ NOT NULL,
    policy_version TEXT NOT NULL
);
CREATE TABLE claim_access.inquiry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    guest_key TEXT NOT NULL UNIQUE REFERENCES claim_access.guest_session(token_hash),
    title TEXT NOT NULL CHECK (char_length(title) BETWEEN 1 AND 120),
    body TEXT NOT NULL CHECK (char_length(body) BETWEEN 1 AND 4000),
    policy_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

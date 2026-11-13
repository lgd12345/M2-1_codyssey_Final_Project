ALTER TABLE claim_access.company ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK(version>0);
ALTER TABLE claim_access.contact ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK(version>0);
ALTER TABLE claim_access.contact ADD COLUMN is_placeholder BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE claim_access.contact ADD CONSTRAINT contact_placeholder_inactive CHECK(NOT(is_placeholder AND is_active));

CREATE TABLE claim_access.equipment (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES claim_access.company(id),
    model_name TEXT NOT NULL CHECK(char_length(model_name) BETWEEN 1 AND 120),
    serial_number TEXT CHECK(char_length(serial_number) BETWEEN 1 AND 120),
    manufacturing_site TEXT CHECK(char_length(manufacturing_site) BETWEEN 1 AND 120),
    is_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('manual','fsr')),
    source_key TEXT UNIQUE CHECK(source_key ~ '^[0-9a-f]{64}$'),
    reference_count INTEGER NOT NULL DEFAULT 0 CHECK(reference_count>=0),
    batch_key UUID,
    batch_index INTEGER,
    batch_hash TEXT CHECK(batch_hash ~ '^[0-9a-f]{64}$'),
    version INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
    UNIQUE(company_id,model_name,serial_number),
    UNIQUE(company_id,batch_key,batch_index),
    CHECK((batch_key IS NULL AND batch_index IS NULL AND batch_hash IS NULL)
          OR (batch_key IS NOT NULL AND batch_index IS NOT NULL AND batch_index>=0 AND batch_hash IS NOT NULL))
);
CREATE INDEX ON claim_access.equipment(company_id,id);
CREATE TABLE claim_access.registry_audit (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id UUID NOT NULL REFERENCES claim_access.company(id),
    actor_id UUID,
    actor_label TEXT NOT NULL,
    event TEXT NOT NULL,
    target_id UUID NOT NULL,
    fields JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON claim_access.registry_audit(company_id,id DESC);

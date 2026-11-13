-- Live service intake only. No management UI, demo seeds or automatic AI runs.
CREATE TABLE service_company (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 200)
);
CREATE TABLE service_company_member (
    user_id UUID PRIMARY KEY REFERENCES app_user(id),
    company_id UUID NOT NULL REFERENCES service_company(id)
);
CREATE INDEX service_company_member_company_idx ON service_company_member(company_id);
CREATE TABLE service_equipment (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES service_company(id),
    machine TEXT NOT NULL CHECK (length(btrim(machine)) BETWEEN 1 AND 120),
    serial TEXT NOT NULL UNIQUE CHECK (length(btrim(serial)) BETWEEN 1 AND 120)
);
CREATE INDEX service_equipment_company_idx ON service_equipment(company_id);
CREATE TABLE service_request (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    equipment_id UUID NOT NULL REFERENCES service_equipment(id),
    company_id UUID NOT NULL REFERENCES service_company(id),
    created_by UUID NOT NULL REFERENCES app_user(id),
    title TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (reason IN ('기계 고장','기술 문의','부품 문의','교육·기술지원')),
    message TEXT NOT NULL CHECK (length(btrim(message)) BETWEEN 1 AND 10000),
    alarm_numbers JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(alarm_numbers) = 'array'),
    contact JSONB NOT NULL CHECK (jsonb_typeof(contact) = 'object'),
    -- Snapshot the actual selected machine at intake; never accept a client-supplied company.
    equipment_snapshot JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT '접수됨' CHECK (status = '접수됨'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX service_request_company_created_idx ON service_request(company_id, created_at DESC, id DESC);

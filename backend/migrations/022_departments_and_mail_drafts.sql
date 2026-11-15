-- Departments an operator can send mail to, and the mail drafts made for a request.
-- Recipient addresses live here (editable data), never in the model's context. Development seed: one test address.
CREATE TABLE service_department (
    key TEXT PRIMARY KEY CHECK (key ~ '^[a-z][a-z0-9_]{1,30}$'),
    name TEXT NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 40),
    description TEXT NOT NULL DEFAULT '',
    recipients TEXT[] NOT NULL DEFAULT '{}',
    active BOOLEAN NOT NULL DEFAULT TRUE
);
INSERT INTO service_department(key,name,description,recipients) VALUES
    ('service', '서비스', '현장 출동·점검이 필요할 때 출동 요청을 보낸다.', ARRAY['hodob76@gmail.com']),
    ('quality', '품질관리', '품질 클레임·재발·재출동 등 품질 보고가 필요할 때 보낸다.', ARRAY['hodob76@gmail.com']),
    ('parts', '부품·자재', '교체 부품 수배가 필요할 때 보낸다.', ARRAY['hodob76@gmail.com']),
    ('sales', '영업', '보증·비용 안내가 필요할 때 보낸다.', ARRAY['hodob76@gmail.com']);

CREATE TABLE service_mail_draft (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id BIGINT NOT NULL REFERENCES service_request(id) ON DELETE CASCADE,
    department_key TEXT NOT NULL REFERENCES service_department(key),
    subject TEXT NOT NULL CHECK (length(btrim(subject)) BETWEEN 1 AND 150 AND subject !~ '[\r\n]'),
    body TEXT NOT NULL CHECK (length(btrim(body)) BETWEEN 1 AND 4000),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'sending', 'sent', 'failed', 'cancelled')),
    created_by UUID REFERENCES app_user(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_by_login TEXT,
    sent_at TIMESTAMPTZ,
    error_code TEXT
);
CREATE INDEX service_mail_draft_request_idx ON service_mail_draft(request_id, id);

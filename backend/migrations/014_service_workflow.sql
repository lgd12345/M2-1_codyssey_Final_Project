-- Review, approval, department work, comments, customer actions and closure on stored requests.
ALTER TABLE service_request DROP CONSTRAINT service_request_status_check;
ALTER TABLE service_request ADD CONSTRAINT service_request_status_check
    CHECK (status IN ('접수됨', '분석 중', '검토 대기', '추가 정보 필요', '처리 중', '반려됨', '종결'));
ALTER TABLE service_request
    ADD COLUMN assignee TEXT,
    ADD COLUMN revision INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN close_requested BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN approval JSONB,
    ADD COLUMN resolution JSONB;
-- A failed re-analysis must return the request to the state it was in before the attempt.
ALTER TABLE service_analysis ADD COLUMN previous_status TEXT NOT NULL DEFAULT '접수됨';

CREATE TABLE service_request_department (
    request_id BIGINT NOT NULL REFERENCES service_request(id) ON DELETE CASCADE,
    key TEXT NOT NULL CHECK (key IN ('service', 'quality', 'parts', 'sales')),
    ai_selected BOOLEAN NOT NULL,
    selected BOOLEAN NOT NULL,
    reason TEXT NOT NULL,
    ai_draft TEXT NOT NULL,
    draft TEXT NOT NULL CHECK (length(draft) <= 10000),
    PRIMARY KEY (request_id, key)
);
CREATE TABLE service_comment (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id BIGINT NOT NULL REFERENCES service_request(id) ON DELETE CASCADE,
    author_id UUID NOT NULL REFERENCES app_user(id),
    author TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('internal', 'public', 'customer')),
    intent TEXT NOT NULL DEFAULT 'reply' CHECK (intent IN ('reply', 'callback', 'close_request')),
    text TEXT NOT NULL CHECK (length(btrim(text)) BETWEEN 1 AND 4000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX service_comment_request_idx ON service_comment(request_id, created_at, id);
CREATE TABLE service_history (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id BIGINT NOT NULL REFERENCES service_request(id) ON DELETE CASCADE,
    at TIMESTAMPTZ NOT NULL DEFAULT now(),
    text TEXT NOT NULL,
    public_text TEXT  -- customer-safe wording; NULL means never shown to customers
);
CREATE INDEX service_history_request_idx ON service_history(request_id, at, id);
CREATE TABLE service_work (
    request_id BIGINT NOT NULL REFERENCES service_request(id) ON DELETE CASCADE,
    dept TEXT NOT NULL CHECK (dept IN ('service', 'quality', 'parts', 'sales')),
    work_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT '전달됨' CHECK (status IN ('전달됨', '진행 중', '완료')),
    content TEXT NOT NULL CHECK (length(btrim(content)) > 0),
    edited BOOLEAN NOT NULL,
    assignee TEXT,
    result JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    done_at TIMESTAMPTZ,
    PRIMARY KEY (request_id, dept),
    CHECK ((status = '완료') = (result IS NOT NULL))
);

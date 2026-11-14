-- Information operators gathered outside the app (phone, on site) for a request, kept append-only with author and time.
-- It feeds re-analysis; customers are never asked for it and never see it.
CREATE TABLE service_additional_info (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id BIGINT NOT NULL REFERENCES service_request(id) ON DELETE CASCADE,
    author_id UUID NOT NULL REFERENCES app_user(id),
    author TEXT NOT NULL,
    text TEXT NOT NULL CHECK (length(btrim(text)) BETWEEN 1 AND 2000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX service_additional_info_request_idx ON service_additional_info(request_id, created_at, id);

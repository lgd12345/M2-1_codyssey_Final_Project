-- One analysis attempt per row. Request status changes with it; approval and department work are not created here.
ALTER TABLE service_request DROP CONSTRAINT service_request_status_check;
ALTER TABLE service_request ADD CONSTRAINT service_request_status_check
    CHECK (status IN ('접수됨', '분석 중', '검토 대기'));
CREATE TABLE service_analysis (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id BIGINT NOT NULL REFERENCES service_request(id) ON DELETE CASCADE,
    requested_by UUID NOT NULL REFERENCES app_user(id),
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed')),
    error_code TEXT,
    result JSONB,
    worker_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    CHECK ((status = 'succeeded') = (result IS NOT NULL)),
    CHECK ((status = 'failed') = (error_code IS NOT NULL))
);
CREATE UNIQUE INDEX service_analysis_one_running_idx ON service_analysis(request_id) WHERE status = 'running';
CREATE INDEX service_analysis_request_idx ON service_analysis(request_id, created_at DESC);

-- Simplified workflow: a request is 접수됨 -> 처리 중 (the moment its first analysis starts) -> 종결.
-- Approval, decline, department work and request assignees are gone. Existing requests keep their data:
-- everything that was in progress (analysing, waiting for review, waiting for information, approved, declined) is 처리 중.
UPDATE service_request SET status='처리 중' WHERE status IN ('분석 중', '검토 대기', '추가 정보 필요', '반려됨');
ALTER TABLE service_request DROP CONSTRAINT service_request_status_check;
ALTER TABLE service_request ADD CONSTRAINT service_request_status_check CHECK (status IN ('접수됨', '처리 중', '종결'));
ALTER TABLE service_request DROP COLUMN assignee, DROP COLUMN approval;

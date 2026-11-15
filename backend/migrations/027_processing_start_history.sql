-- Keep the processing transition and its customer-visible history aligned.
-- Existing history timestamps (including old approval-era starts) are preserved.
UPDATE service_history
SET public_text = '담당부서에서 처리를 시작했습니다.'
WHERE public_text IN ('처리를 시작했습니다.', '담당 부서에서 처리를 시작했습니다.')
   OR (public_text IS NULL AND text = '처리 시작 · 분석 시작');

-- Repair only starts evidenced by a recorded transition from 접수됨.
-- Do not invent a start for requests with no such record; never enqueue mail.
INSERT INTO service_history(request_id, at, text, public_text)
SELECT r.id, first_start.at, '처리 시작 · 분석 시작', '담당부서에서 처리를 시작했습니다.'
FROM service_request r
JOIN (
    SELECT request_id, min(created_at) AS at
    FROM service_analysis
    WHERE previous_status = '접수됨'
    GROUP BY request_id
) first_start ON first_start.request_id = r.id
WHERE r.status IN ('처리 중', '종결')
  AND NOT EXISTS (
      SELECT 1 FROM service_history h
      WHERE h.request_id = r.id
        AND h.public_text = '담당부서에서 처리를 시작했습니다.'
  );

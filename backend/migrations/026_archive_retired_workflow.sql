-- Retired notes/replies, department review copies and department work are no longer used by the application.
-- Preserve historical rows and their relationships without exposing them through the active public schema.
CREATE SCHEMA service_legacy;
ALTER TABLE public.service_comment SET SCHEMA service_legacy;
ALTER TABLE public.service_request_department SET SCHEMA service_legacy;
ALTER TABLE public.service_work SET SCHEMA service_legacy;
COMMENT ON SCHEMA service_legacy IS 'Historical retired workflow data. No application reads or writes.';

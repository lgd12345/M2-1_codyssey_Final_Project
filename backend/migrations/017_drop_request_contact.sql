-- Intake identifies its author via created_by (authenticated account), not another identity/contact form.
ALTER TABLE service_request DROP COLUMN contact;

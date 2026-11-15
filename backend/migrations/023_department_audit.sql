-- Who last changed a department's addresses or settings, and when (departments are now edited from the app).
ALTER TABLE service_department
    ADD COLUMN updated_by TEXT,
    ADD COLUMN updated_at TIMESTAMPTZ;

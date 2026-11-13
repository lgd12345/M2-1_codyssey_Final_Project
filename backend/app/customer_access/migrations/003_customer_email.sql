-- Explicit management only. Preserve all legacy IDs and add email support for customers.
DO $$
DECLARE current_rule TEXT;
BEGIN
    IF to_regclass('app_user') IS DISTINCT FROM to_regclass('public.app_user')
       OR to_regclass('public.app_user') IS NULL THEN
        RAISE EXCEPTION 'Expected public.app_user on the explicitly selected auth database';
    END IF;
    SELECT pg_get_constraintdef(oid) INTO current_rule FROM pg_constraint
        WHERE conrelid='public.app_user'::regclass AND conname='app_user_login_id_check';
    IF current_rule IS NULL OR current_rule <> 'CHECK ((login_id ~ ''^[a-z0-9._@-]{3,64}$''::text))' THEN
        RAISE EXCEPTION 'Login constraint differs; inspect before applying';
    END IF;
END $$;
ALTER TABLE public.app_user DROP CONSTRAINT app_user_login_id_check;
ALTER TABLE public.app_user ADD CONSTRAINT app_user_login_id_check CHECK (
    login_id ~ '^[a-z0-9._@-]{3,64}$'
    OR (role='customer' AND char_length(login_id) BETWEEN 3 AND 254
        AND login_id ~ '^[a-z0-9.!#$%&''*+/=?^_`{|}~-]+@[a-z0-9.-]+$')
);

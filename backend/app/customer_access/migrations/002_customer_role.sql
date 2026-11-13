-- Explicit auth-DB management step only. Never executed by web startup.
-- Existing admin/user accounts remain manually issued operator accounts.
DO $$
DECLARE current_rule TEXT;
BEGIN
    IF to_regclass('app_user') IS DISTINCT FROM to_regclass('public.app_user')
       OR to_regclass('public.app_user') IS NULL THEN
        RAISE EXCEPTION 'Expected public.app_user on the explicitly selected auth database';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.app_user'::regclass AND conname='app_user_role_check') THEN
        RAISE EXCEPTION 'Existing role constraint differs; inspect before applying';
    END IF;
    SELECT pg_get_constraintdef(oid) INTO current_rule FROM pg_constraint
        WHERE conrelid='public.app_user'::regclass AND conname='app_user_role_check';
    IF current_rule <> 'CHECK ((role = ANY (ARRAY[''admin''::text, ''user''::text])))' THEN
        RAISE EXCEPTION 'Role constraint definition differs; review instead of weakening an unknown rule';
    END IF;
END $$;
ALTER TABLE public.app_user DROP CONSTRAINT app_user_role_check;
ALTER TABLE public.app_user ADD CONSTRAINT app_user_role_check CHECK (role IN ('admin','user','customer'));

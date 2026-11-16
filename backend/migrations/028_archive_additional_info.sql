-- Retire operator-added facts without discarding historical data.
-- Application input is now the customer's original request only.
ALTER TABLE public.service_additional_info SET SCHEMA service_legacy;
COMMENT ON TABLE service_legacy.service_additional_info IS 'Retired operator facts. No application reads or writes.';

CREATE TABLE service_legacy.service_additional_info_proposal
    (LIKE public.service_chat_proposal INCLUDING ALL);
ALTER TABLE service_legacy.service_additional_info_proposal
    ADD FOREIGN KEY (request_id) REFERENCES public.service_request(id) ON DELETE CASCADE;
INSERT INTO service_legacy.service_additional_info_proposal OVERRIDING SYSTEM VALUE
    SELECT * FROM public.service_chat_proposal WHERE kind = 'add_info';
DELETE FROM public.service_chat_proposal WHERE kind = 'add_info';
ALTER TABLE public.service_chat_proposal
    DROP CONSTRAINT service_chat_proposal_kind_check,
    ADD CONSTRAINT service_chat_proposal_kind_check CHECK (kind = 'reanalysis');
COMMENT ON TABLE service_legacy.service_additional_info_proposal IS 'Retired proposals, including pending ones. No application execution.';

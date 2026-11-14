-- Replace company-specific demo equipment with a shared model catalogue.
-- Destructive scope explicitly approved: old service requests and their dependent records, demo equipment.
DELETE FROM service_request;
DELETE FROM service_equipment;
ALTER TABLE service_equipment DROP COLUMN company_id, DROP COLUMN serial;
ALTER TABLE service_equipment ADD CONSTRAINT service_equipment_machine_unique UNIQUE(machine);
ALTER TABLE service_request DROP CONSTRAINT service_request_reason_check;
ALTER TABLE service_request ADD CONSTRAINT service_request_reason_check CHECK (reason IN (
 '공구 교환 이상','스핀들 이상','이송축 이상','유압·공압·윤활 이상','알람·전장 이상','가공 정밀도 이상','부품 교체·문의','교육·기술지원','기타 증상'));

-- A third answer status for replies that assert no manual facts (greetings, clarifying questions).
-- It is stored and shown as "no manual evidence"; answers that do claim manual facts still need citations.
ALTER TABLE agent_run DROP CONSTRAINT IF EXISTS agent_run_answer_status_check;
ALTER TABLE agent_run ADD CONSTRAINT agent_run_answer_status_check
    CHECK (answer_status IS NULL OR answer_status IN ('answered', 'insufficient_evidence', 'conversational'));

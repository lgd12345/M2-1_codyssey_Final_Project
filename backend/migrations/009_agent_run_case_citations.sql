-- Past service cases (FSR) the agent cited in a validated answer; manual page citations stay in `citations`.
ALTER TABLE agent_run ADD COLUMN IF NOT EXISTS case_citations JSONB NOT NULL DEFAULT '[]'::jsonb;

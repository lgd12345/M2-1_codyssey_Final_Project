-- Document kind was guessed from file names, which is unreliable and decided what got indexed.
-- Identifier rules now read the text itself; narrowing is by machine, which the data states.
ALTER TABLE rag_document DROP COLUMN IF EXISTS document_kind;

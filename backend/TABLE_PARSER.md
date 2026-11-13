# Markdown table parser

`app/agent_rag/tables.py` parses converted manual Markdown, not original PDF geometry.
It is a lossless structural view: it does not normalize numbers, fill merged cells,
remove repeated content, overwrite source pages, or change embedding hashes.

## Applied paths

- `search_manual` results include `table_evidence` alongside unchanged content and sources.
- `lookup_identifier` matches and `open_source` return the same structural evidence.
- Parts/drawing identifier extraction during future ingestion uses the parser instead
  of naive `split('|')`. Ragged rows and ambiguous identifier headers are not indexed.
  Existing identifier rows are not automatically rebuilt.
- Agent instructions require original-PDF checks for malformed/truncated tables and
  forbid treating blank cells as ditto or treating parser output as PDF-verified.

## Supported / intentionally not inferred

- Header + Markdown delimiter, optional outer pipes, alignment markers.
- Escaped pipes and pipes inside matched backtick spans do not shift columns.
- Empty first/last/interior cells, numeric strings, leading zeroes and HTML breaks remain literal.
- Multiple/adjacent tables; tables inside fenced code are ignored.
- Motor model headers and additional specification/ID rows remain in their original
  positions; multi-row/merged header semantics are not guessed. When the explicit
  header is `Motor model`, consecutive leading `Motor specification`, `Motor ID No.`
  and `PRM NO`/`SERVO PRM` rows are retained in `context_rows` even when query row
  selection omits other rows. Only these recognized leading rows (up to eight) are
  treated as context; similarly named body cells are not promoted.
- HTML rowspan/colspan is not reconstructed; detectable HTML spans are flagged.
- No OCR/layout recovery, no split-column reconciliation, no automatic duplicate removal.

`table_evidence` returns original line ranges, headers, row indices and cell arrays.
Query-matching body rows are prioritized; context rows are separate from the body
row budget. Limits and omitted rows/tables/columns or truncated cells are reported
explicitly (`max_columns` defaults to 32 and applies to headers/context/body alike).
`rows_omitted` excludes the separately returned context rows. The full parser retains
all columns, including malformed extra cells; evidence limits only affect presentation. Full source text is still available. Warnings include:
`ragged_rows`, `empty_headers`, `duplicate_headers`, `repeated_long_cells`,
`oversized_cell`, `html_spans_unresolved`.

## Read-only corpus audit

From `backend`, using the configured RAG database:

```bash
python scripts/audit_tables.py --output /path/outside/repo/table_audit.jsonl
```

The script opens a read-only transaction, reads unique manual content and emits
summary counts plus anomaly locations. It makes no embedding calls or database writes.
The report has document/page references but no full text. Warnings do not prove corruption.

Reviewed embedding input corrections remain a separate explicit operation via
`scripts/reviewed_embedding_inputs.py`; this parser does not apply them automatically.

"""Read-only audit of Markdown tables in existing manual pages. No re-ingest or embedding calls."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent_rag.db import connect_database
from app.agent_rag.settings import AgentSettings
from app.agent_rag.tables import parse_tables


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='JSONL anomalies, with document/page references but no full text')
    args = parser.parse_args()
    counts = Counter()
    connection = connect_database(AgentSettings.from_env().database_url)
    output = None
    try:
        connection.execute('SET TRANSACTION READ ONLY')
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            output = args.output.open('w', encoding='utf-8')
        with connection.cursor(name='table_audit') as cursor:
            cursor.execute('''SELECT p.content_hash,min(p.content),
                jsonb_agg(jsonb_build_object('document',d.title,'pdf_page',p.pdf_page))
                FROM rag_page p JOIN rag_document d USING(source_sha256)
                WHERE p.content<>'' GROUP BY p.content_hash ORDER BY p.content_hash''')
            for digest, content, sources in cursor:
                counts['unique_contents'] += 1
                tables = parse_tables(content)
                counts['contents_with_tables'] += bool(tables)
                counts['tables'] += len(tables)
                for i, table in enumerate(tables, 1):
                    counts['rows'] += len(table.rows)
                    for warning in table.warnings:
                        counts[warning] += 1
                    if table.warnings and output:
                        output.write(json.dumps(dict(content_hash=digest, sources=sources, table_index=i,
                            start_line=table.start_line,end_line=table.end_line,
                            column_count=len(table.headers),row_count=len(table.rows),
                            warnings=table.warnings), ensure_ascii=False)+'\n')
        print(json.dumps(dict(counts), ensure_ascii=False, indent=2))
    finally:
        if output:
            output.close()
        connection.rollback()
        connection.close()


if __name__ == '__main__':
    main()

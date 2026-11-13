from test_retrieval_db import test_db, _document, _page, ingest_documents
from app.agent_rag.retrieval import lookup_identifier, search_manual


def test_search_and_identifier_lookup_return_structured_table_without_rewriting_content(test_db):
    text = '| NO. | PART NO. | NAME |\n| --- | --- | --- |\n| 1 | SM1101012035 | SPINDLE MOTOR |'
    page = _page(1, 'table', text)
    ingest_documents([_document('c'*64, 'F400', [page])], connection=test_db)
    found = lookup_identifier('SM1101012035', connection=test_db)
    assert found['found']
    evidence = found['matches'][0]['table_evidence']
    assert evidence['tables'][0]['headers'] == ['NO.', 'PART NO.', 'NAME']
    assert evidence['tables'][0]['rows'][0]['cells'] == ['1', 'SM1101012035', 'SPINDLE MOTOR']
    result = search_manual('SM1101012035', connection=test_db)['results'][0]
    assert result['table_evidence'] == evidence
    assert result['content'] == page.content
    assert test_db.execute('SELECT content_hash,content FROM rag_page').fetchone() == (page.content_hash, page.content)

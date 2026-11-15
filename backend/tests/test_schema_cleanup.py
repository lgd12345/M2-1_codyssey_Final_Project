"""The schema carries only what the product uses. Run ONLY through scripts/test_isolated.py (disposable DB)."""
import pytest

from test_retrieval_db import test_db  # noqa: F401


def exists(connection, table):
    return connection.execute('SELECT to_regclass(%s)', (f'public.{table}',)).fetchone()[0] is not None


@pytest.mark.parametrize('table', ['agent_run', 'agent_run_asset', 'service_analysis_feedback'])
def test_the_retired_agent_run_store_is_gone(test_db, table):
    assert not exists(test_db, table)


@pytest.mark.parametrize('table', ['service_request', 'service_analysis', 'service_department',
                                   'rag_document', 'rag_page', 'rag_case', 'app_user'])
def test_what_the_product_uses_is_still_there(test_db, table):
    assert exists(test_db, table)


@pytest.mark.parametrize('table', ['service_comment', 'service_work', 'service_request_department'])
def test_retired_workflow_tables_are_archived_not_active(test_db, table):
    assert not exists(test_db, table)
    assert test_db.execute('SELECT to_regclass(%s)', (f'service_legacy.{table}',)).fetchone()[0] is not None

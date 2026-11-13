import json

import pytest

from scripts import embedding_status


class Connection:
    def rollback(self):
        pass

    def close(self):
        pass

    def execute(self, sql, *_args):
        assert sql.startswith('SET TRANSACTION READ ONLY') or sql.startswith('SELECT current_database')
        return self

    def fetchone(self):
        return ('service_poc_test',)


@pytest.mark.parametrize('status,code', [('ready', 0), ('config_mismatch', 1), ('incomplete', 1), ('not_indexed', 1)])
def test_status_exit_code_is_nonzero_unless_runtime_and_active_index_agree(monkeypatch, capsys, status, code):
    class Embedder:
        identity = {}
        config_id = 'cfg'
    monkeypatch.setattr(embedding_status, 'connect_for_status', lambda: Connection())
    monkeypatch.setattr(embedding_status, 'configured_embedder', lambda provider=None, **_: Embedder())
    monkeypatch.setattr(embedding_status, 'embedding_readiness', lambda *_: {'status': status, 'embedder_missing': 0})
    assert embedding_status.main(['--provider', 'qwen']) == code
    output = json.loads(capsys.readouterr().out)
    assert output['status'] == status and output['database'] == 'service_poc_test'
    assert 'password' not in json.dumps(output).lower()

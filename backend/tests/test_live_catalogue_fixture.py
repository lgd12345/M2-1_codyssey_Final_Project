"""Live-runner preparation uses shared models and an isolated foreign request, never removed equipment columns."""
from uuid import uuid4

from scripts import test_live_intake as runner


class Connection:
    def __init__(self):
        self.admin, self.user, self.model, self.company = (uuid4() for _ in range(4))
        self.queries = []
        self.result = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def execute(self, sql, params=()):
        self.queries.append((sql, params))
        assert 'serial' not in sql and 'e.company_id' not in sql
        if 'current_database()' in sql:
            self.result = [('service_poc_test',)]
        elif 'FROM app_user' in sql:
            self.result = [(self.admin, 'admin', 'admin', True), (self.user, 'user', 'user', True)]
        elif 'FROM service_company_member' in sql:
            self.result = [(self.company,)]
        elif 'FROM service_equipment' in sql:
            self.result = [(self.model, 'VMCT-02')]
        elif 'INSERT INTO service_company' in sql:
            self.result = [(uuid4(),)]
        elif 'INSERT INTO service_request' in sql:
            self.result = [(901,)]
        elif 'DELETE FROM service_request' in sql:
            self.rowcount = 2
        elif 'DELETE FROM service_company' in sql:
            self.rowcount = 1
        else:
            raise AssertionError(sql)
        return self

    def fetchone(self):
        return self.result[0] if self.result else None

    def __iter__(self):
        return iter(self.result)


def test_live_fixture_never_creates_or_deletes_shared_models(monkeypatch):
    db = Connection()
    monkeypatch.setattr(runner.psycopg, 'connect', lambda *_a, **_kw: db)
    fixture = runner.prepare('synthetic')
    assert fixture['user_equipment_id'] == str(db.model)
    assert fixture['foreign_request_id'] == 'CLM-901'
    assert runner.cleanup('synthetic', fixture) == 2
    statements = '\n'.join(q for q, _ in db.queries)
    assert 'INSERT INTO service_equipment' not in statements
    assert 'DELETE FROM service_equipment' not in statements
    assert 'left(message,length(%s))=%s' in statements

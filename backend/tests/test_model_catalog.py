"""CSV catalogue includes models even when their FSR cases would be filtered out."""
import csv
import pytest
import psycopg
from app.service_requests.model_catalog import csv_models, import_models
from test_service_requests_api import setup, DSN, BASE, body


def test_csv_models_are_all_trimmed_unique_sorted_not_filtered_by_resolution(tmp_path):
    path = tmp_path / 'source.csv'
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerows([['기종명', '진행현황', '호기'], [' VMCT-02 ', '', 'private'],
                         ['VMCT-01', 'x', 'private'], ['VMCT-02', '', 'other'], ['', '', '']])
    assert csv_models(path) == ['VMCT-01', 'VMCT-02']


def test_missing_csv_model_column_is_not_silently_accepted(tmp_path):
    path = tmp_path / 'invalid.csv'
    path.write_text('wrong\nvalue\n')
    with pytest.raises(ValueError, match='기종명'):
        csv_models(path)


@pytest.mark.skipif(not DSN, reason='isolated database required')
def test_import_is_idempotent_models_shared_but_requests_remain_company_private(setup, tmp_path):
    clients, _ = setup
    path = tmp_path / 'models.csv'
    path.write_text('기종명\nVMCT-01\nVMCT-02\nVMCT-01\n', encoding='utf-8-sig')
    try:
        with psycopg.connect(DSN) as db:
            import_models(db, path)
            import_models(db, path)
            assert db.execute("SELECT count(*) FROM service_equipment WHERE machine LIKE 'VMCT-%'").fetchone()[0] == 2
        contexts = [clients[who].get(f'{BASE}/context').json() for who in ['alice', 'bob', 'staff']]
        assert contexts[0]['equipment'] == contexts[1]['equipment'] == contexts[2]['equipment']
        model = next(m for m in contexts[0]['equipment'] if m['machine'] == 'VMCT-01')
        assert set(model) == {'id', 'machine'}
        item = clients['alice'].post(BASE, json=body(model['id'])).json()
        assert item['intake']['machine'] == 'VMCT-01'
        assert 'serial' not in item['intake']
        assert clients['bob'].get(f"{BASE}/{item['id']}").status_code == 404
        assert clients['alice'].post(BASE, json={**body(model['id']), 'reason': '기계 고장'}).status_code == 422
    finally:
        with psycopg.connect(DSN) as db:
            db.execute("DELETE FROM service_request WHERE equipment_id IN (SELECT id FROM service_equipment WHERE machine LIKE 'VMCT-%')")
            db.execute("DELETE FROM service_equipment WHERE machine LIKE 'VMCT-%'")

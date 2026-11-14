"""Import ALL nonempty CSV model names, independently of RAG case filtering."""
import csv


def csv_models(path):
    with open(path, encoding='utf-8-sig', newline='') as source:
        rows = csv.DictReader(source)
        if '기종명' not in (rows.fieldnames or []):
            raise ValueError('CSV requires 기종명 column')
        models = sorted({row['기종명'].strip() for row in rows if row.get('기종명', '').strip()})
    if not models or any(len(model) > 120 for model in models):
        raise ValueError('CSV must contain valid model names (1–120 characters)')
    return models


def import_models(connection, path):
    models = csv_models(path)
    for model in models:
        connection.execute('INSERT INTO service_equipment(machine) VALUES (%s) ON CONFLICT(machine) DO NOTHING', (model,))
    return models
